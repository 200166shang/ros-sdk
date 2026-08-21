#include "navigation_task_manager.hpp"

#include <utility>

namespace ros2_sdk::skeleton {

NavigationTaskManager::NavigationTaskManager(std::shared_ptr<TaskEventHub> event_hub)
    : event_hub_(std::move(event_hub)) {}

void NavigationTaskManager::set_adapter(std::shared_ptr<NavigationAdapter> adapter) {
  std::lock_guard<std::mutex> lock(mutex_);
  adapter_ = std::move(adapter);
}

NavigationTask NavigationTaskManager::start(const std::string& target_name) {
  const NavigationTask task = create(target_name);
  const auto adapter = this->adapter();
  if (adapter) {
    adapter->start(task);
  } else {
    handle_adapter_event(NavigationAdapterEvent{
        task.task_id, NavigationAdapterEventKind::kResult, NavigationResultCode::kUnknown,
        "navigation adapter is not configured", "",
        NavigationOutcome{NavigationOutcomeCode::kInternalError,
                          "navigation adapter is not configured"}});
  }
  return get(task.task_id).value_or(task);
}

bool NavigationTaskManager::action_server_ready(std::chrono::milliseconds timeout) const {
  const auto adapter = this->adapter();
  return adapter && adapter->action_server_ready(timeout);
}

NavigationTask NavigationTaskManager::create(const std::string& target_name) {
  std::lock_guard<std::mutex> lock(mutex_);
  NavigationTask task;
  task.task_id = "navigation-" + std::to_string(next_id_++);
  task.target_name = target_name;
  task.state = TaskState::kAccepted;
  task.message = "navigation task accepted";
  tasks_.emplace(task.task_id, task);
  publish(task);
  return task;
}

std::optional<NavigationTask> NavigationTaskManager::get(const std::string& task_id) const {
  std::lock_guard<std::mutex> lock(mutex_);
  const auto iterator = tasks_.find(task_id);
  if (iterator == tasks_.end()) {
    return std::nullopt;
  }
  return iterator->second;
}

bool NavigationTaskManager::transition(const std::string& task_id, TaskState state,
                                       std::string message,
                                       std::optional<NavigationOutcome> outcome) {
  std::lock_guard<std::mutex> lock(mutex_);
  const auto iterator = tasks_.find(task_id);
  if (iterator == tasks_.end() ||
      !transition_locked(iterator->second, state, std::move(message), std::move(outcome))) {
    return false;
  }
  publish(iterator->second);
  return true;
}

NavigationTaskManager::CancelResult NavigationTaskManager::cancel(const std::string& task_id) {
  NavigationTask task;
  std::shared_ptr<NavigationAdapter> adapter;
  {
    std::lock_guard<std::mutex> lock(mutex_);
    const auto iterator = tasks_.find(task_id);
    if (iterator == tasks_.end()) {
      return {CancelStatus::kNotFound, std::nullopt};
    }
    task = iterator->second;
    if (task.state == TaskState::kCanceling) {
      return {CancelStatus::kAlreadyCanceling, task};
    }
    if (task.state == TaskState::kCanceled) {
      return {CancelStatus::kAlreadyCanceled, task};
    }
    if (is_terminal(task.state)) {
      return {CancelStatus::kTerminal, task};
    }
    if (!transition_locked(iterator->second, TaskState::kCanceling,
                           "navigation cancellation requested", std::nullopt)) {
      return {CancelStatus::kTerminal, task};
    }
    task = iterator->second;
    publish(task);
    adapter = adapter_;
  }
  if (adapter) {
    adapter->cancel(task_id);
  }
  return {CancelStatus::kRequested, get(task_id)};
}

bool NavigationTaskManager::update_feedback(const std::string& task_id, std::string feedback) {
  std::lock_guard<std::mutex> lock(mutex_);
  const auto iterator = tasks_.find(task_id);
  if (iterator == tasks_.end() || is_terminal(iterator->second.state)) {
    return false;
  }
  iterator->second.feedback = std::move(feedback);
  publish(iterator->second, TaskEventKind::kFeedback);
  return true;
}

void NavigationTaskManager::handle_adapter_event(const NavigationAdapterEvent& event) {
  std::lock_guard<std::mutex> lock(mutex_);
  const auto iterator = tasks_.find(event.task_id);
  if (iterator == tasks_.end() || is_terminal(iterator->second.state)) {
    return;
  }
  auto& task = iterator->second;

  switch (event.kind) {
    case NavigationAdapterEventKind::kGoalAccepted:
      if (task.state == TaskState::kAccepted &&
          transition_locked(task, TaskState::kRunning,
                            event.message.empty() ? "Nav2 goal accepted" : event.message,
                            std::nullopt)) {
        publish(task);
      }
      return;
    case NavigationAdapterEventKind::kGoalRejected:
      if (task.state == TaskState::kCanceling) {
        if (transition_locked(
                task, TaskState::kCanceled, event.message,
                NavigationOutcome{NavigationOutcomeCode::kCanceled, "navigation was canceled"})) {
          publish(task);
        }
      } else if (task.state == TaskState::kAccepted &&
                 transition_locked(task, TaskState::kRejected, event.message,
                                   event.outcome.value_or(NavigationOutcome{
                                       NavigationOutcomeCode::kGoalRejected, event.message}))) {
        publish(task);
      }
      return;
    case NavigationAdapterEventKind::kFeedback:
      task.feedback = event.feedback;
      publish(task, TaskEventKind::kFeedback);
      return;
    case NavigationAdapterEventKind::kCancelRejected:
      if (task.state == TaskState::kCanceling &&
          transition_locked(task, TaskState::kFailed, event.message,
                            event.outcome.value_or(NavigationOutcome{
                                NavigationOutcomeCode::kInternalError, event.message}))) {
        publish(task);
      }
      return;
    case NavigationAdapterEventKind::kResult: {
      TaskState state = TaskState::kFailed;
      NavigationOutcome outcome = event.outcome.value_or(
          NavigationOutcome{NavigationOutcomeCode::kInternalError, event.message});
      switch (event.result_code) {
        case NavigationResultCode::kSucceeded:
          if (task.state != TaskState::kRunning && task.state != TaskState::kCanceling) {
            return;
          }
          state = TaskState::kSucceeded;
          outcome = event.outcome.value_or(
              NavigationOutcome{NavigationOutcomeCode::kSucceeded, event.message});
          break;
        case NavigationResultCode::kCanceled:
          if (task.state == TaskState::kCanceling) {
            state = TaskState::kCanceled;
            outcome = event.outcome.value_or(
                NavigationOutcome{NavigationOutcomeCode::kCanceled, event.message});
          } else {
            outcome = NavigationOutcome{NavigationOutcomeCode::kFailed,
                                        "Nav2 returned CANCELED without a cancellation request"};
          }
          break;
        case NavigationResultCode::kAborted:
          outcome = event.outcome.value_or(
              NavigationOutcome{NavigationOutcomeCode::kAborted, event.message});
          break;
        case NavigationResultCode::kUnknown:
          break;
      }
      if (transition_locked(task, state, outcome.message, outcome)) {
        publish(task);
      }
      return;
    }
  }
}

bool NavigationTaskManager::transition_locked(NavigationTask& task, TaskState state,
                                              std::string message,
                                              std::optional<NavigationOutcome> outcome) {
  if (task.state == state) {
    if (is_terminal(task.state)) {
      return false;
    }
    task.message = std::move(message);
    task.outcome = std::move(outcome);
    return true;
  }
  if (is_terminal(task.state)) {
    return false;
  }

  const bool accepted_transition =
      (task.state == TaskState::kAccepted &&
       (state == TaskState::kRunning || state == TaskState::kCanceling ||
        state == TaskState::kRejected || state == TaskState::kFailed)) ||
      (task.state == TaskState::kRunning &&
       (state == TaskState::kCanceling || state == TaskState::kSucceeded ||
        state == TaskState::kCanceled || state == TaskState::kFailed)) ||
      (task.state == TaskState::kCanceling &&
       (state == TaskState::kCanceled || state == TaskState::kSucceeded ||
        state == TaskState::kFailed));
  if (!accepted_transition) {
    return false;
  }
  task.state = state;
  task.message = std::move(message);
  task.outcome = std::move(outcome);
  return true;
}

void NavigationTaskManager::publish(const NavigationTask& task, TaskEventKind kind) const {
  event_hub_->publish(TaskEvent{task, kind});
}

std::shared_ptr<NavigationAdapter> NavigationTaskManager::adapter() const {
  std::lock_guard<std::mutex> lock(mutex_);
  return adapter_;
}

}  // namespace ros2_sdk::skeleton
