#include "delivery_service.hpp"

#include <cmath>
#include <mutex>
#include <nav2_msgs/action/navigate_to_pose.hpp>
#include <rclcpp_action/rclcpp_action.hpp>
#include <utility>

namespace ros2_sdk {

namespace {

constexpr auto kNavigationTimeout = std::chrono::seconds(30);
constexpr char kNavigationTimeoutReason[] = "navigation exceeded the 30 second time limit";

geometry_msgs::msg::PoseStamped make_location(double x, double y) {
  geometry_msgs::msg::PoseStamped target;
  target.header.frame_id = "map";
  target.pose.position.x = x;
  target.pose.position.y = y;
  target.pose.orientation.w = 1.0;
  return target;
}

class Nav2NavigationAdapter final : public NavigationPort {
public:
  using Action = nav2_msgs::action::NavigateToPose;
  using GoalHandle = rclcpp_action::ClientGoalHandle<Action>;

  explicit Nav2NavigationAdapter(rclcpp::Node::SharedPtr node)
      : node_(std::move(node)),
        action_client_(rclcpp_action::create_client<Action>(node_, "navigate_to_pose")) {}

  bool ready(std::chrono::milliseconds timeout) const override {
    return action_client_->wait_for_action_server(timeout);
  }

  void navigate(const geometry_msgs::msg::PoseStamped& target, FeedbackCallback feedback_callback,
                ResultCallback result_callback) override {
    Action::Goal goal;
    goal.pose = target;
    goal.pose.header.stamp = node_->get_clock()->now();

    {
      std::lock_guard<std::mutex> lock(goal_mutex_);
      active_goal_.reset();
      cancel_requested_ = false;
      timeout_requested_ = false;
      timeout_timer_ = node_->create_wall_timer(kNavigationTimeout, [this] { handle_timeout(); });
    }

    rclcpp_action::Client<Action>::SendGoalOptions options;
    options.goal_response_callback = [this, result_callback](const GoalHandle::SharedPtr& handle) {
      if (handle == nullptr) {
        bool timed_out = false;
        {
          std::lock_guard<std::mutex> lock(goal_mutex_);
          timed_out = timeout_requested_;
          timeout_requested_ = false;
          if (timeout_timer_ != nullptr) {
            timeout_timer_->cancel();
          }
        }
        result_callback(timed_out ? Outcome::kTimedOut : Outcome::kFailed);
        return;
      }

      bool cancel_requested = false;
      bool timeout_requested = false;
      {
        std::lock_guard<std::mutex> lock(goal_mutex_);
        active_goal_ = handle;
        cancel_requested = cancel_requested_;
        timeout_requested = timeout_requested_;
      }
      if (cancel_requested || timeout_requested) {
        (void)action_client_->async_cancel_goal(handle);
      }
    };
    options.feedback_callback = [feedback_callback](
                                    const GoalHandle::SharedPtr&,
                                    const std::shared_ptr<const Action::Feedback>& feedback) {
      if (std::isfinite(feedback->distance_remaining)) {
        feedback_callback(feedback->distance_remaining);
      }
    };
    options.result_callback = [this, result_callback](const GoalHandle::WrappedResult& result) {
      bool timed_out = false;
      {
        std::lock_guard<std::mutex> lock(goal_mutex_);
        timed_out = timeout_requested_;
        active_goal_.reset();
        cancel_requested_ = false;
        timeout_requested_ = false;
        if (timeout_timer_ != nullptr) {
          timeout_timer_->cancel();
        }
      }
      if (result.code == rclcpp_action::ResultCode::SUCCEEDED) {
        result_callback(Outcome::kSucceeded);
      } else if (timed_out) {
        result_callback(Outcome::kTimedOut);
      } else if (result.code == rclcpp_action::ResultCode::CANCELED) {
        result_callback(Outcome::kCanceled);
      } else {
        result_callback(Outcome::kFailed);
      }
    };

    (void)action_client_->async_send_goal(goal, options);
  }

  void cancel() override {
    GoalHandle::SharedPtr active_goal;
    {
      std::lock_guard<std::mutex> lock(goal_mutex_);
      cancel_requested_ = true;
      active_goal = active_goal_;
    }
    if (active_goal != nullptr) {
      (void)action_client_->async_cancel_goal(active_goal);
    }
  }

private:
  void handle_timeout() {
    GoalHandle::SharedPtr active_goal;
    {
      std::lock_guard<std::mutex> lock(goal_mutex_);
      if (cancel_requested_ || timeout_requested_) {
        return;
      }
      timeout_requested_ = true;
      active_goal = active_goal_;
    }
    if (active_goal != nullptr) {
      (void)action_client_->async_cancel_goal(active_goal);
    }
  }

  rclcpp::Node::SharedPtr node_;
  rclcpp_action::Client<Action>::SharedPtr action_client_;
  mutable std::mutex goal_mutex_;
  GoalHandle::SharedPtr active_goal_;
  bool cancel_requested_{false};
  bool timeout_requested_{false};
  rclcpp::TimerBase::SharedPtr timeout_timer_;
};

}  // namespace

DeliveryService::DeliveryService(rclcpp::Node::SharedPtr node)
    : node_(node), navigation_(std::make_shared<Nav2NavigationAdapter>(std::move(node))) {}

DeliveryService::DeliveryService(std::shared_ptr<NavigationPort> navigation)
    : navigation_(std::move(navigation)) {}

bool DeliveryService::ready(std::chrono::milliseconds timeout) const {
  return navigation_ != nullptr && navigation_->ready(timeout);
}

grpc::Status DeliveryService::CreateDelivery(grpc::ServerContext* /*context*/,
                                             const delivery::CreateDeliveryRequest* request,
                                             delivery::DeliverySnapshot* response) {
  if (request->request_id().empty()) {
    return grpc::Status(grpc::StatusCode::INVALID_ARGUMENT, "request_id is required");
  }

  {
    std::lock_guard<std::mutex> lock(mutex_);
    if (active_task_.has_value() && active_task_->request_id == request->request_id()) {
      if (active_task_->pickup_location == request->pickup_location() &&
          active_task_->dropoff_location == request->dropoff_location()) {
        fill_snapshot(*active_task_, response);
        return grpc::Status::OK;
      }
      return grpc::Status(grpc::StatusCode::ALREADY_EXISTS,
                          "CONFLICT: request_id was used with different parameters");
    }
  }

  const auto pickup = resolve_location(request->pickup_location());
  const auto dropoff = resolve_location(request->dropoff_location());
  if (!pickup.has_value() || !dropoff.has_value()) {
    return grpc::Status(
        grpc::StatusCode::INVALID_ARGUMENT,
        "INVALID_LOCATION: pickup and dropoff locations must be known fixed locations");
  }

  DeliveryTask task;
  {
    std::lock_guard<std::mutex> lock(mutex_);
    if (active_task_.has_value() && active_task_->request_id == request->request_id()) {
      if (active_task_->pickup_location == request->pickup_location() &&
          active_task_->dropoff_location == request->dropoff_location()) {
        fill_snapshot(*active_task_, response);
        return grpc::Status::OK;
      }
      return grpc::Status(grpc::StatusCode::ALREADY_EXISTS,
                          "CONFLICT: request_id was used with different parameters");
    }

    if (active_task_.has_value() && !is_terminal(active_task_->state)) {
      return grpc::Status(grpc::StatusCode::RESOURCE_EXHAUSTED,
                          "BUSY: an active delivery already occupies the robot");
    }
    if (navigation_ == nullptr || !navigation_->ready(std::chrono::milliseconds(0))) {
      return grpc::Status(grpc::StatusCode::FAILED_PRECONDITION,
                          "NOT_READY: delivery navigation capability is not ready");
    }

    task.task_id = "task-" + std::to_string(next_task_number_++);
    task.request_id = request->request_id();
    task.pickup_location = request->pickup_location();
    task.dropoff_location = request->dropoff_location();
    task.state = delivery::STARTING;
    active_task_ = task;
  }

  fill_snapshot(task, response);
  start_navigation(task.task_id, *pickup, delivery::NAVIGATING_TO_PICKUP);
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

grpc::Status DeliveryService::ConfirmPickup(grpc::ServerContext* /*context*/,
                                            const delivery::ConfirmDeliveryRequest* request,
                                            delivery::DeliverySnapshot* response) {
  DeliveryTask task;
  std::optional<geometry_msgs::msg::PoseStamped> dropoff;
  bool start_dropoff_navigation = false;
  {
    std::lock_guard<std::mutex> lock(mutex_);
    if (!active_task_.has_value() || active_task_->task_id != request->task_id()) {
      return grpc::Status(grpc::StatusCode::NOT_FOUND, "delivery task was not found");
    }

    const auto state = active_task_->state;
    const bool confirmation_already_applied = state == delivery::NAVIGATING_TO_DROPOFF ||
                                              state == delivery::AWAITING_DROPOFF_CONFIRMATION ||
                                              state == delivery::COMPLETED;
    if (state != delivery::AWAITING_PICKUP_CONFIRMATION && !confirmation_already_applied) {
      return invalid_state("pickup confirmation is not valid in the current delivery state");
    }

    if (state == delivery::AWAITING_PICKUP_CONFIRMATION) {
      dropoff = resolve_location(active_task_->dropoff_location);
      if (!dropoff.has_value()) {
        return grpc::Status(grpc::StatusCode::INTERNAL, "dropoff location is no longer known");
      }
      start_dropoff_navigation = true;
      active_task_->state = delivery::NAVIGATING_TO_DROPOFF;
      active_task_->current_target = active_task_->dropoff_location;
      active_task_->remaining_distance_m.reset();
    }
    task = *active_task_;
  }

  fill_snapshot(task, response);
  if (start_dropoff_navigation) {
    start_navigation(task.task_id, *dropoff, delivery::NAVIGATING_TO_DROPOFF);
  }
  return grpc::Status::OK;
}

grpc::Status DeliveryService::ConfirmDropoff(grpc::ServerContext* /*context*/,
                                             const delivery::ConfirmDeliveryRequest* request,
                                             delivery::DeliverySnapshot* response) {
  std::lock_guard<std::mutex> lock(mutex_);
  if (!active_task_.has_value() || active_task_->task_id != request->task_id()) {
    return grpc::Status(grpc::StatusCode::NOT_FOUND, "delivery task was not found");
  }

  if (active_task_->state == delivery::COMPLETED) {
    fill_snapshot(*active_task_, response);
    return grpc::Status::OK;
  }
  if (active_task_->state != delivery::AWAITING_DROPOFF_CONFIRMATION) {
    return invalid_state("dropoff confirmation is not valid in the current delivery state");
  }

  active_task_->state = delivery::COMPLETED;
  active_task_->current_target.clear();
  active_task_->remaining_distance_m.reset();
  fill_snapshot(*active_task_, response);
  return grpc::Status::OK;
}

grpc::Status DeliveryService::CancelDelivery(grpc::ServerContext* /*context*/,
                                             const delivery::CancelDeliveryRequest* request,
                                             delivery::DeliverySnapshot* response) {
  bool cancel_navigation = false;
  {
    std::lock_guard<std::mutex> lock(mutex_);
    if (!active_task_.has_value() || active_task_->task_id != request->task_id()) {
      return grpc::Status(grpc::StatusCode::NOT_FOUND, "delivery task was not found");
    }

    if (is_terminal(active_task_->state) || active_task_->state == delivery::CANCELING) {
      fill_snapshot(*active_task_, response);
      return grpc::Status::OK;
    }

    if (is_navigating(active_task_->state) || active_task_->state == delivery::STARTING) {
      active_task_->state = delivery::CANCELING;
      cancel_navigation = true;
    } else {
      active_task_->state = delivery::CANCELED;
      active_task_->current_target.clear();
      active_task_->remaining_distance_m.reset();
    }
    fill_snapshot(*active_task_, response);
  }

  if (cancel_navigation) {
    navigation_->cancel();
  }
  return grpc::Status::OK;
}

std::optional<geometry_msgs::msg::PoseStamped> DeliveryService::resolve_location(
    const std::string& location_name) {
  if (location_name == "pickup_a") {
    return make_location(0.5, -0.5);
  }
  if (location_name == "dropoff_a") {
    return make_location(0.48, -0.46);
  }
  if (location_name == "unreachable_a") {
    return make_location(20.0, 20.0);
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
  } else {
    response->clear_remaining_distance_m();
  }
  response->set_failure_code(task.failure_code);
  response->set_failure_reason(task.failure_reason);
}

bool DeliveryService::is_terminal(delivery::DeliveryState state) {
  return state == delivery::COMPLETED || state == delivery::CANCELED || state == delivery::FAILED;
}

bool DeliveryService::is_navigating(delivery::DeliveryState state) {
  return state == delivery::NAVIGATING_TO_PICKUP || state == delivery::NAVIGATING_TO_DROPOFF;
}

grpc::Status DeliveryService::invalid_state(const char* reason) {
  return grpc::Status(grpc::StatusCode::FAILED_PRECONDITION,
                      std::string("INVALID_STATE: ") + reason);
}

void DeliveryService::start_navigation(const std::string& task_id,
                                       const geometry_msgs::msg::PoseStamped& target,
                                       delivery::DeliveryState navigating_state) {
  {
    std::lock_guard<std::mutex> lock(mutex_);
    if (!active_task_.has_value() || active_task_->task_id != task_id) {
      return;
    }
    if ((navigating_state == delivery::NAVIGATING_TO_PICKUP &&
         active_task_->state != delivery::STARTING) ||
        (navigating_state == delivery::NAVIGATING_TO_DROPOFF &&
         active_task_->state != delivery::NAVIGATING_TO_DROPOFF)) {
      return;
    }
    active_task_->state = navigating_state;
    active_task_->current_target = navigating_state == delivery::NAVIGATING_TO_PICKUP
                                       ? active_task_->pickup_location
                                       : active_task_->dropoff_location;
    active_task_->remaining_distance_m.reset();
  }

  const std::weak_ptr<DeliveryService> weak_self = weak_from_this();
  const auto feedback_callback = [weak_self, task_id](double distance_remaining) {
    if (const auto self = weak_self.lock()) {
      self->handle_feedback(task_id, distance_remaining);
    }
  };
  const auto result_callback = [weak_self, task_id,
                                navigating_state](NavigationPort::Outcome outcome) {
    if (const auto self = weak_self.lock()) {
      self->handle_result(task_id, navigating_state, outcome);
    }
  };
  navigation_->navigate(target, feedback_callback, result_callback);
}

void DeliveryService::handle_feedback(const std::string& task_id, double distance_remaining) {
  if (!std::isfinite(distance_remaining)) {
    return;
  }

  std::lock_guard<std::mutex> lock(mutex_);
  if (active_task_.has_value() && active_task_->task_id == task_id &&
      (active_task_->state == delivery::NAVIGATING_TO_PICKUP ||
       active_task_->state == delivery::NAVIGATING_TO_DROPOFF)) {
    active_task_->remaining_distance_m = distance_remaining;
  }
}

// NOLINTNEXTLINE(readability-function-cognitive-complexity)
void DeliveryService::handle_result(const std::string& task_id,
                                    delivery::DeliveryState navigating_state,
                                    NavigationPort::Outcome outcome) {
  if (outcome == NavigationPort::Outcome::kCanceled) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (active_task_.has_value() && active_task_->task_id == task_id) {
      if (active_task_->state == delivery::CANCELING) {
        active_task_->state = delivery::CANCELED;
        active_task_->current_target.clear();
        active_task_->remaining_distance_m.reset();
      } else if (active_task_->state == navigating_state) {
        active_task_->state = delivery::FAILED;
        active_task_->current_target.clear();
        active_task_->remaining_distance_m.reset();
        active_task_->failure_code = "UNREACHABLE";
        active_task_->failure_reason = "navigation goal did not succeed";
      }
    }
    return;
  }

  if (outcome == NavigationPort::Outcome::kTimedOut) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (active_task_.has_value() && active_task_->task_id == task_id &&
        (active_task_->state == navigating_state || active_task_->state == delivery::CANCELING)) {
      active_task_->state = delivery::FAILED;
      active_task_->current_target.clear();
      active_task_->remaining_distance_m.reset();
      active_task_->failure_code = "NAVIGATION_TIMEOUT";
      active_task_->failure_reason = kNavigationTimeoutReason;
    }
    return;
  }

  if (outcome == NavigationPort::Outcome::kFailed) {
    if (node_ != nullptr) {
      RCLCPP_ERROR(node_->get_logger(), "Nav2 delivery goal did not succeed for %s",
                   task_id.c_str());
    }
    std::lock_guard<std::mutex> lock(mutex_);
    if (active_task_.has_value() && active_task_->task_id == task_id &&
        (active_task_->state == navigating_state || active_task_->state == delivery::CANCELING)) {
      active_task_->state = delivery::FAILED;
      active_task_->current_target.clear();
      active_task_->remaining_distance_m.reset();
      active_task_->failure_code = "UNREACHABLE";
      active_task_->failure_reason = "navigation goal did not succeed";
    }
    return;
  }

  std::lock_guard<std::mutex> lock(mutex_);
  if (!active_task_.has_value() || active_task_->task_id != task_id ||
      active_task_->state != navigating_state) {
    return;
  }

  active_task_->state = navigating_state == delivery::NAVIGATING_TO_PICKUP
                            ? delivery::AWAITING_PICKUP_CONFIRMATION
                            : delivery::AWAITING_DROPOFF_CONFIRMATION;
  active_task_->current_target.clear();
  active_task_->remaining_distance_m.reset();
}

}  // namespace ros2_sdk
