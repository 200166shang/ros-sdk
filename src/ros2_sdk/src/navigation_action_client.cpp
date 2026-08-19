#include "navigation_action_client.hpp"

#include <algorithm>
#include <exception>
#include <utility>

namespace ros2_sdk::skeleton {

NavigationActionClient::NavigationActionClient(rclcpp::Node::SharedPtr node,
                                               std::chrono::milliseconds action_server_timeout,
                                               const std::string& action_name)
    : node_(std::move(node)),
      client_(rclcpp_action::create_client<Action>(node_, action_name)),
      action_server_timeout_(action_server_timeout) {}

NavigationOutcome NavigationActionClient::navigate(const std::string& target_name,
                                                   std::chrono::milliseconds timeout,
                                                   const CancellationPredicate& is_cancelled) {
  const auto target = resolve_target(*node_, target_name);
  if (!target.has_value()) {
    return {NavigationOutcomeCode::kInvalidTarget, "unknown fixed target: " + target_name};
  }

  if (!action_server_ready(action_server_timeout_)) {
    return {NavigationOutcomeCode::kActionServerUnavailable,
            "NavigateToPose action server is unavailable"};
  }

  const auto pending = std::make_shared<PendingRequest>();
  const std::weak_ptr<NavigationActionClient> weak_self = weak_from_this();

  Action::Goal goal;
  goal.pose = *target;

  rclcpp_action::Client<Action>::SendGoalOptions options;
  options.goal_response_callback = [weak_self, pending](const GoalHandle::SharedPtr& handle) {
    if (!handle) {
      complete(pending, {NavigationOutcomeCode::kGoalRejected, "Nav2 rejected the goal"});
      return;
    }

    bool cancel_late_goal = false;
    {
      std::lock_guard<std::mutex> lock(pending->mutex);
      pending->goal_handle = handle;
      cancel_late_goal = pending->terminal;
    }

    if (cancel_late_goal) {
      if (const auto self = weak_self.lock()) {
        (void)self->client_->async_cancel_goal(handle);
      }
    }
  };
  options.feedback_callback = [](const GoalHandle::SharedPtr&,
                                 const std::shared_ptr<const Action::Feedback>&) {
  };
  options.result_callback = [pending](const GoalHandle::WrappedResult& result) {
    complete(pending, map_result(result));
  };

  try {
    (void)client_->async_send_goal(goal, options);
  } catch (const std::exception& exception) {
    return {NavigationOutcomeCode::kInternalError,
            std::string("failed to send Nav2 goal: ") + exception.what()};
  }

  std::unique_lock<std::mutex> lock(pending->mutex);
  const auto deadline = std::chrono::steady_clock::now() + timeout;
  while (!pending->terminal) {
    if (is_cancelled && is_cancelled()) {
      break;
    }

    const auto now = std::chrono::steady_clock::now();
    if (now >= deadline) {
      break;
    }

    const auto remaining = std::chrono::duration_cast<std::chrono::milliseconds>(deadline - now);
    pending->condition.wait_for(lock, std::min(remaining, std::chrono::milliseconds(100)));
  }

  if (!pending->terminal) {
    const bool request_cancelled = is_cancelled && is_cancelled();
    const NavigationOutcome cancellation_or_timeout =
        request_cancelled
            ? NavigationOutcome{NavigationOutcomeCode::kAborted, "navigation request was canceled"}
            : NavigationOutcome{NavigationOutcomeCode::kTimeout, "Nav2 goal timed out"};
    pending->terminal = true;
    pending->outcome = cancellation_or_timeout;
    const NavigationOutcome terminal_outcome = *pending->outcome;
    const auto goal_handle = pending->goal_handle;
    lock.unlock();
    if (goal_handle) {
      (void)client_->async_cancel_goal(goal_handle);
    }
    return terminal_outcome;
  }

  return *pending->outcome;
}

bool NavigationActionClient::action_server_ready(std::chrono::milliseconds timeout) {
  return client_->wait_for_action_server(timeout);
}

std::optional<geometry_msgs::msg::PoseStamped> NavigationActionClient::resolve_target(
    const rclcpp::Node& node, const std::string& target_name) {
  if (target_name != "pickup_a") {
    return std::nullopt;
  }

  geometry_msgs::msg::PoseStamped target;
  target.header.frame_id = "map";
  target.header.stamp = node.get_clock()->now();
  target.pose.position.x = 1.7;
  target.pose.position.y = -1.5;
  target.pose.orientation.w = 1.0;
  return target;
}

void NavigationActionClient::complete(const std::shared_ptr<PendingRequest>& pending,
                                      NavigationOutcome outcome) {
  {
    std::lock_guard<std::mutex> lock(pending->mutex);
    if (pending->terminal) {
      return;
    }
    pending->terminal = true;
    pending->outcome = std::move(outcome);
  }
  pending->condition.notify_one();
}

NavigationOutcome NavigationActionClient::map_result(const GoalHandle::WrappedResult& result) {
  switch (result.code) {
    case rclcpp_action::ResultCode::SUCCEEDED:
      return {NavigationOutcomeCode::kSucceeded, "Nav2 goal succeeded"};
    case rclcpp_action::ResultCode::CANCELED:
      return {NavigationOutcomeCode::kAborted, "Nav2 goal was canceled"};
    case rclcpp_action::ResultCode::ABORTED:
      return {NavigationOutcomeCode::kAborted, "Nav2 aborted the goal"};
    default:
      return {NavigationOutcomeCode::kInternalError, "Nav2 returned an unknown result"};
  }
}

}  // namespace ros2_sdk::skeleton
