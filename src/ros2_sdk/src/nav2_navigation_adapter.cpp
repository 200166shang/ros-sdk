#include "nav2_navigation_adapter.hpp"

#include <exception>
#include <utility>

namespace ros2_sdk::skeleton {

Nav2NavigationAdapter::Nav2NavigationAdapter(rclcpp::Node::SharedPtr node,
                                             NavigationAdapterEventCallback event_callback,
                                             std::chrono::milliseconds action_server_timeout,
                                             const std::string& action_name)
    : NavigationAdapter(std::move(event_callback)),
      node_(std::move(node)),
      client_(rclcpp_action::create_client<Action>(node_, action_name)),
      action_server_timeout_(action_server_timeout) {}

void Nav2NavigationAdapter::start(const NavigationTask& task) {
  {
    std::lock_guard<std::mutex> lock(mutex_);
    active_goals_.emplace(task.task_id, ActiveGoal{});
  }

  const auto target = target_catalog_.resolve(task.target_name);
  if (!target.has_value()) {
    std::lock_guard<std::mutex> lock(mutex_);
    active_goals_.erase(task.task_id);
    const std::string message = "unknown fixed target: " + task.target_name;
    emit_event(NavigationAdapterEvent{
        task.task_id, NavigationAdapterEventKind::kGoalRejected, NavigationResultCode::kUnknown,
        message, "", NavigationOutcome{NavigationOutcomeCode::kInvalidTarget, message}});
    return;
  }
  if (!action_server_ready(std::chrono::milliseconds(0))) {
    std::lock_guard<std::mutex> lock(mutex_);
    active_goals_.erase(task.task_id);
    const std::string message = "NavigateToPose action server is unavailable";
    emit_event(NavigationAdapterEvent{
        task.task_id, NavigationAdapterEventKind::kResult, NavigationResultCode::kUnknown, message,
        "", NavigationOutcome{NavigationOutcomeCode::kActionServerUnavailable, message}});
    return;
  }

  Action::Goal goal;
  goal.pose = *target;
  goal.pose.header.stamp = node_->get_clock()->now();

  rclcpp_action::Client<Action>::SendGoalOptions options;
  const std::weak_ptr<Nav2NavigationAdapter> weak_self = weak_from_this();
  options.goal_response_callback = [weak_self,
                                    task_id = task.task_id](const GoalHandle::SharedPtr& handle) {
    if (const auto self = weak_self.lock()) {
      self->handle_goal_response(task_id, handle);
    }
  };
  options.feedback_callback = [weak_self, task_id = task.task_id](
                                  const GoalHandle::SharedPtr&,
                                  const std::shared_ptr<const Action::Feedback>& feedback) {
    if (const auto self = weak_self.lock()) {
      self->handle_feedback(task_id, *feedback);
    }
  };
  options.result_callback = [weak_self,
                             task_id = task.task_id](const GoalHandle::WrappedResult& result) {
    if (const auto self = weak_self.lock()) {
      self->handle_result(task_id, result);
    }
  };

  try {
    (void)client_->async_send_goal(goal, options);
  } catch (const std::exception& exception) {
    {
      std::lock_guard<std::mutex> lock(mutex_);
      active_goals_.erase(task.task_id);
    }
    const std::string message = std::string("failed to send Nav2 goal: ") + exception.what();
    emit_event(NavigationAdapterEvent{
        task.task_id, NavigationAdapterEventKind::kResult, NavigationResultCode::kUnknown, message,
        "", NavigationOutcome{NavigationOutcomeCode::kInternalError, message}});
  }
}

void Nav2NavigationAdapter::handle_feedback(const std::string& task_id,
                                            const Action::Feedback& feedback) {
  emit_event(NavigationAdapterEvent{
      task_id, NavigationAdapterEventKind::kFeedback, NavigationResultCode::kUnknown, "",
      "distance_remaining=" + std::to_string(feedback.distance_remaining), std::nullopt});
}

void Nav2NavigationAdapter::cancel(const std::string& task_id) {
  GoalHandle::SharedPtr goal_handle;
  {
    std::lock_guard<std::mutex> lock(mutex_);
    const auto iterator = active_goals_.find(task_id);
    if (iterator == active_goals_.end()) {
      return;
    }
    iterator->second.cancel_requested = true;
    goal_handle = iterator->second.goal_handle;
  }
  cancel_goal_if_needed(task_id, goal_handle);
}

bool Nav2NavigationAdapter::action_server_ready(std::chrono::milliseconds timeout) {
  return client_->wait_for_action_server(timeout);
}

void Nav2NavigationAdapter::handle_goal_response(const std::string& task_id,
                                                 const GoalHandle::SharedPtr& goal_handle) {
  if (!goal_handle) {
    {
      std::lock_guard<std::mutex> lock(mutex_);
      active_goals_.erase(task_id);
    }
    emit_event(NavigationAdapterEvent{
        task_id, NavigationAdapterEventKind::kGoalRejected, NavigationResultCode::kUnknown,
        "Nav2 rejected the goal", "",
        NavigationOutcome{NavigationOutcomeCode::kGoalRejected, "Nav2 rejected the goal"}});
    return;
  }

  bool cancel_requested = false;
  {
    std::lock_guard<std::mutex> lock(mutex_);
    const auto iterator = active_goals_.find(task_id);
    if (iterator == active_goals_.end()) {
      return;
    }
    iterator->second.goal_handle = goal_handle;
    cancel_requested = iterator->second.cancel_requested;
  }
  emit_event(NavigationAdapterEvent{task_id, NavigationAdapterEventKind::kGoalAccepted,
                                    NavigationResultCode::kUnknown, "Nav2 goal accepted", "",
                                    std::nullopt});
  if (cancel_requested) {
    cancel_goal_if_needed(task_id, goal_handle);
  }
}

void Nav2NavigationAdapter::handle_result(const std::string& task_id,
                                          const GoalHandle::WrappedResult& result) {
  {
    std::lock_guard<std::mutex> lock(mutex_);
    active_goals_.erase(task_id);
  }
  const NavigationResultCode code = result_code(result);
  NavigationOutcome outcome;
  switch (code) {
    case NavigationResultCode::kSucceeded:
      outcome = {NavigationOutcomeCode::kSucceeded, "Nav2 goal succeeded"};
      break;
    case NavigationResultCode::kCanceled:
      outcome = {NavigationOutcomeCode::kCanceled, "Nav2 goal was canceled"};
      break;
    case NavigationResultCode::kAborted:
      outcome = {NavigationOutcomeCode::kAborted, "Nav2 goal was aborted"};
      break;
    case NavigationResultCode::kUnknown:
      outcome = {NavigationOutcomeCode::kInternalError, "Nav2 returned an unknown result"};
      break;
  }
  emit_event(NavigationAdapterEvent{task_id, NavigationAdapterEventKind::kResult, code,
                                    outcome.message, "", outcome});
}

void Nav2NavigationAdapter::cancel_goal_if_needed(const std::string& task_id,
                                                  const GoalHandle::SharedPtr& goal_handle) {
  if (!goal_handle) {
    return;
  }
  bool send_cancel = false;
  {
    std::lock_guard<std::mutex> lock(mutex_);
    const auto iterator = active_goals_.find(task_id);
    if (iterator != active_goals_.end() && iterator->second.cancel_requested &&
        !iterator->second.cancel_sent) {
      iterator->second.cancel_sent = true;
      send_cancel = true;
    }
  }
  if (send_cancel) {
    const std::weak_ptr<Nav2NavigationAdapter> weak_self = weak_from_this();
    (void)client_->async_cancel_goal(goal_handle, [weak_self, task_id](const auto& response) {
      if (response && response->return_code == 0) {
        return;
      }
      if (const auto self = weak_self.lock()) {
        self->emit_event(NavigationAdapterEvent{
            task_id, NavigationAdapterEventKind::kCancelRejected, NavigationResultCode::kUnknown,
            "Nav2 rejected goal cancellation", "",
            NavigationOutcome{NavigationOutcomeCode::kInternalError,
                              "Nav2 rejected goal cancellation"}});
      }
    });
  }
}

NavigationResultCode Nav2NavigationAdapter::result_code(const GoalHandle::WrappedResult& result) {
  switch (result.code) {
    case rclcpp_action::ResultCode::SUCCEEDED:
      return NavigationResultCode::kSucceeded;
    case rclcpp_action::ResultCode::CANCELED:
      return NavigationResultCode::kCanceled;
    case rclcpp_action::ResultCode::ABORTED:
      return NavigationResultCode::kAborted;
    default:
      return NavigationResultCode::kUnknown;
  }
}

}  // namespace ros2_sdk::skeleton
