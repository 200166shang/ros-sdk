#include "navigation_service.hpp"

#include <chrono>
#include <utility>

namespace ros2_sdk::skeleton {

namespace {

ros2_sdk::api::NavigationTaskState to_proto_state(TaskState state) {
  switch (state) {
    case TaskState::kAccepted:
      return ros2_sdk::api::TASK_ACCEPTED;
    case TaskState::kRunning:
      return ros2_sdk::api::TASK_RUNNING;
    case TaskState::kCanceling:
      return ros2_sdk::api::TASK_CANCELING;
    case TaskState::kSucceeded:
      return ros2_sdk::api::TASK_SUCCEEDED;
    case TaskState::kCanceled:
      return ros2_sdk::api::TASK_CANCELED;
    case TaskState::kRejected:
      return ros2_sdk::api::TASK_REJECTED;
    case TaskState::kFailed:
      return ros2_sdk::api::TASK_FAILED;
  }
  return ros2_sdk::api::TASK_STATE_UNSPECIFIED;
}

ros2_sdk::api::NavigationOutcome::Code to_proto_outcome(NavigationOutcomeCode code) {
  switch (code) {
    case NavigationOutcomeCode::kSucceeded:
      return ros2_sdk::api::NavigationOutcome::OUTCOME_SUCCEEDED;
    case NavigationOutcomeCode::kInvalidTarget:
      return ros2_sdk::api::NavigationOutcome::OUTCOME_INVALID_TARGET;
    case NavigationOutcomeCode::kActionServerUnavailable:
      return ros2_sdk::api::NavigationOutcome::OUTCOME_ACTION_SERVER_UNAVAILABLE;
    case NavigationOutcomeCode::kGoalRejected:
      return ros2_sdk::api::NavigationOutcome::OUTCOME_GOAL_REJECTED;
    case NavigationOutcomeCode::kAborted:
      return ros2_sdk::api::NavigationOutcome::OUTCOME_ABORTED;
    case NavigationOutcomeCode::kTimeout:
      return ros2_sdk::api::NavigationOutcome::OUTCOME_TIMEOUT;
    case NavigationOutcomeCode::kInternalError:
      return ros2_sdk::api::NavigationOutcome::OUTCOME_INTERNAL_ERROR;
    case NavigationOutcomeCode::kCanceled:
      return ros2_sdk::api::NavigationOutcome::OUTCOME_CANCELED;
    case NavigationOutcomeCode::kFailed:
      return ros2_sdk::api::NavigationOutcome::OUTCOME_FAILED;
  }
  return ros2_sdk::api::NavigationOutcome::OUTCOME_UNSPECIFIED;
}

}  // namespace

NavigationService::NavigationService(std::shared_ptr<NavigationTaskManager> task_manager)
    : task_manager_(std::move(task_manager)) {}

grpc::Status NavigationService::Health(grpc::ServerContext* /*context*/,
                                       const ros2_sdk::api::HealthRequest* /*request*/,
                                       ros2_sdk::api::HealthResponse* response) {
  const bool ready = task_manager_->action_server_ready(std::chrono::milliseconds(0));
  response->set_ready(ready);
  response->set_message(ready ? "NavigateToPose is ready" : "NavigateToPose is unavailable");
  return grpc::Status::OK;
}

grpc::Status NavigationService::StartNavigation(grpc::ServerContext* /*context*/,
                                                const ros2_sdk::api::StartNavigationRequest* request,
                                                ros2_sdk::api::StartNavigationResponse* response) {
  if (request->target_name().empty()) {
    return grpc::Status(grpc::StatusCode::INVALID_ARGUMENT, "target_name is required");
  }
  const NavigationTask task = task_manager_->start(request->target_name());
  fill_task(task, response->mutable_task());
  return grpc::Status::OK;
}

grpc::Status NavigationService::GetNavigation(grpc::ServerContext* /*context*/,
                                              const ros2_sdk::api::GetNavigationRequest* request,
                                              ros2_sdk::api::GetNavigationResponse* response) {
  const auto task = task_manager_->get(request->task_id());
  if (!task.has_value()) {
    return grpc::Status(grpc::StatusCode::NOT_FOUND, "navigation task was not found");
  }
  fill_task(*task, response->mutable_task());
  return grpc::Status::OK;
}

grpc::Status NavigationService::CancelNavigation(
    grpc::ServerContext* /*context*/, const ros2_sdk::api::CancelNavigationRequest* request,
    ros2_sdk::api::CancelNavigationResponse* response) {
  const auto task = task_manager_->get(request->task_id());
  if (!task.has_value()) {
    return grpc::Status(grpc::StatusCode::NOT_FOUND, "navigation task was not found");
  }
  const auto cancel_result = task_manager_->cancel(request->task_id());
  if (cancel_result.status == NavigationTaskManager::CancelStatus::kNotFound) {
    return grpc::Status(grpc::StatusCode::NOT_FOUND, "navigation task was not found");
  }
  if (cancel_result.status == NavigationTaskManager::CancelStatus::kTerminal) {
    return grpc::Status(grpc::StatusCode::FAILED_PRECONDITION,
                        "navigation task is already terminal");
  }
  fill_task(*cancel_result.task, response->mutable_task());
  return grpc::Status::OK;
}

grpc::Status NavigationService::WatchNavigation(
    grpc::ServerContext* context, const ros2_sdk::api::WatchNavigationRequest* request,
    grpc::ServerWriter<ros2_sdk::api::NavigationEvent>* writer) {
  if (!task_manager_->get(request->task_id()).has_value()) {
    return grpc::Status(grpc::StatusCode::NOT_FOUND, "navigation task was not found");
  }
  const auto subscription = task_manager_->event_hub()->subscribe(request->task_id());
  if (!subscription) {
    return grpc::Status(grpc::StatusCode::UNAVAILABLE, "navigation event hub is closed");
  }
  const auto initial = task_manager_->get(request->task_id());
  if (initial.has_value()) {
    subscription->push(TaskEvent{*initial});
  }

  TaskEvent event;
  while (subscription->next(&event,
                            [context] { return context != nullptr && context->IsCancelled(); })) {
    ros2_sdk::api::NavigationEvent proto_event;
    fill_task(event.task, proto_event.mutable_task());
    if (!writer->Write(proto_event) || is_terminal(event.task)) {
      break;
    }
  }
  subscription->close();
  return grpc::Status::OK;
}

void NavigationService::fill_task(const NavigationTask& task,
                                  ros2_sdk::api::NavigationTask* proto_task) {
  proto_task->set_task_id(task.task_id);
  proto_task->set_target_name(task.target_name);
  proto_task->set_state(to_proto_state(task.state));
  proto_task->set_message(task.message);
  proto_task->set_feedback(task.feedback);
  if (task.outcome.has_value()) {
    auto* outcome = proto_task->mutable_outcome();
    outcome->set_code(to_proto_outcome(task.outcome->code));
    outcome->set_message(task.outcome->message);
  }
}

bool NavigationService::is_terminal(const NavigationTask& task) {
  return ros2_sdk::skeleton::is_terminal(task.state);
}

}  // namespace ros2_sdk::skeleton
