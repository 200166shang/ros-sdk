#include "delivery_service.hpp"

#include <cmath>
#include <utility>

namespace ros2_sdk {

namespace {

geometry_msgs::msg::PoseStamped make_location(double x, double y) {
  geometry_msgs::msg::PoseStamped target;
  target.header.frame_id = "map";
  target.pose.position.x = x;
  target.pose.position.y = y;
  target.pose.orientation.w = 1.0;
  return target;
}

}  // namespace

DeliveryService::DeliveryService(rclcpp::Node::SharedPtr node)
    : node_(std::move(node)),
      action_client_(rclcpp_action::create_client<Action>(node_, "navigate_to_pose")) {}

bool DeliveryService::ready(std::chrono::milliseconds timeout) const {
  return action_client_->wait_for_action_server(timeout);
}

grpc::Status DeliveryService::CreateDelivery(grpc::ServerContext* /*context*/,
                                             const delivery::CreateDeliveryRequest* request,
                                             delivery::DeliverySnapshot* response) {
  if (request->request_id().empty()) {
    return grpc::Status(grpc::StatusCode::INVALID_ARGUMENT, "request_id is required");
  }

  const auto pickup = resolve_location(request->pickup_location());
  const auto dropoff = resolve_location(request->dropoff_location());
  if (!pickup.has_value() || !dropoff.has_value()) {
    return grpc::Status(grpc::StatusCode::INVALID_ARGUMENT,
                        "pickup and dropoff locations must be known fixed locations");
  }

  DeliveryTask task;
  {
    std::lock_guard<std::mutex> lock(mutex_);
    if (active_task_.has_value()) {
      return grpc::Status(grpc::StatusCode::RESOURCE_EXHAUSTED,
                          "an active delivery already occupies the robot");
    }

    task.task_id = "task-" + std::to_string(next_task_number_++);
    task.request_id = request->request_id();
    task.pickup_location = request->pickup_location();
    task.dropoff_location = request->dropoff_location();
    task.state = delivery::STARTING;
    active_task_ = task;
  }

  fill_snapshot(task, response);
  start_pickup_navigation(task.task_id, *pickup);
  return grpc::Status::OK;
}

grpc::Status DeliveryService::GetDelivery(grpc::ServerContext* /*context*/,
                                          const delivery::GetDeliveryRequest* request,
                                          delivery::DeliverySnapshot* response) {
  std::lock_guard<std::mutex> lock(mutex_);
  if (!active_task_.has_value() || active_task_->task_id != request->task_id()) {
    return grpc::Status(grpc::StatusCode::NOT_FOUND, "delivery task was not found");
  }

  fill_snapshot(*active_task_, response);
  return grpc::Status::OK;
}

std::optional<geometry_msgs::msg::PoseStamped> DeliveryService::resolve_location(
    const std::string& location_name) {
  if (location_name == "pickup_a") {
    return make_location(0.8, -1.8);
  }
  if (location_name == "dropoff_a") {
    return make_location(-1.5, -1.5);
  }
  return std::nullopt;
}

void DeliveryService::fill_snapshot(const DeliveryTask& task,
                                    delivery::DeliverySnapshot* response) {
  response->set_task_id(task.task_id);
  response->set_request_id(task.request_id);
  response->set_pickup_location(task.pickup_location);
  response->set_dropoff_location(task.dropoff_location);
  response->set_state(task.state);
  response->set_current_target(task.current_target);
  if (task.remaining_distance_m.has_value()) {
    response->set_remaining_distance_m(*task.remaining_distance_m);
  }
}

void DeliveryService::start_pickup_navigation(const std::string& task_id,
                                              const geometry_msgs::msg::PoseStamped& target) {
  {
    std::lock_guard<std::mutex> lock(mutex_);
    if (!active_task_.has_value() || active_task_->task_id != task_id) {
      return;
    }
    active_task_->state = delivery::NAVIGATING_TO_PICKUP;
    active_task_->current_target = active_task_->pickup_location;
    active_task_->remaining_distance_m.reset();
  }

  Action::Goal goal;
  goal.pose = target;
  goal.pose.header.stamp = node_->get_clock()->now();

  rclcpp_action::Client<Action>::SendGoalOptions options;
  const std::weak_ptr<DeliveryService> weak_self = weak_from_this();
  options.goal_response_callback = [weak_self, task_id](const GoalHandle::SharedPtr& handle) {
    if (const auto self = weak_self.lock()) {
      self->handle_goal_response(task_id, handle);
    }
  };
  options.feedback_callback = [weak_self, task_id](
                                  const GoalHandle::SharedPtr&,
                                  const std::shared_ptr<const Action::Feedback>& feedback) {
    if (const auto self = weak_self.lock()) {
      self->handle_feedback(task_id, *feedback);
    }
  };
  options.result_callback = [weak_self, task_id](const GoalHandle::WrappedResult& result) {
    if (const auto self = weak_self.lock()) {
      self->handle_result(task_id, result);
    }
  };

  (void)action_client_->async_send_goal(goal, options);
}

// NOLINTNEXTLINE(readability-function-cognitive-complexity)
void DeliveryService::handle_goal_response(const std::string& task_id,
                                           const GoalHandle::SharedPtr& goal_handle) {
  if (goal_handle == nullptr) {
    RCLCPP_ERROR(node_->get_logger(), "Nav2 rejected delivery pickup goal %s", task_id.c_str());
  }
}

void DeliveryService::handle_feedback(const std::string& task_id,
                                      const Action::Feedback& feedback) {
  if (!std::isfinite(feedback.distance_remaining)) {
    return;
  }

  std::lock_guard<std::mutex> lock(mutex_);
  if (active_task_.has_value() && active_task_->task_id == task_id &&
      active_task_->state == delivery::NAVIGATING_TO_PICKUP) {
    active_task_->remaining_distance_m = feedback.distance_remaining;
  }
}

// NOLINTNEXTLINE(readability-function-cognitive-complexity)
void DeliveryService::handle_result(const std::string& task_id,
                                    const GoalHandle::WrappedResult& result) {
  if (result.code != rclcpp_action::ResultCode::SUCCEEDED) {
    RCLCPP_ERROR(node_->get_logger(), "Nav2 pickup goal did not succeed for %s", task_id.c_str());
    return;
  }

  std::lock_guard<std::mutex> lock(mutex_);
  if (active_task_.has_value() && active_task_->task_id == task_id) {
    active_task_->state = delivery::AWAITING_PICKUP_CONFIRMATION;
    active_task_->current_target.clear();
    active_task_->remaining_distance_m.reset();
  }
}

}  // namespace ros2_sdk
