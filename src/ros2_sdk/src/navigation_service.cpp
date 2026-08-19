#include "navigation_service.hpp"

#include <chrono>
#include <utility>

namespace ros2_sdk::skeleton {

NavigationService::NavigationService(std::shared_ptr<NavigationActionClient> action_client)
    : action_client_(std::move(action_client)) {}

grpc::Status NavigationService::Health(grpc::ServerContext* /*context*/,
                                       const HealthRequest* /*request*/, HealthResponse* response) {
  const bool ready = action_client_->action_server_ready(std::chrono::milliseconds(0));
  response->set_ready(ready);
  response->set_message(ready ? "NavigateToPose is ready" : "NavigateToPose is unavailable");
  return grpc::Status::OK;
}

grpc::Status NavigationService::Navigate(grpc::ServerContext* context,
                                         const NavigateRequest* request,
                                         NavigateResponse* response) {
  const NavigationOutcome outcome =
      action_client_->navigate(request->target_name(), std::chrono::seconds(60),
                               [context] { return context != nullptr && context->IsCancelled(); });
  response->set_message(outcome.message);

  switch (outcome.code) {
    case NavigationOutcomeCode::kSucceeded:
      response->set_outcome(NavigateResponse::SUCCEEDED);
      break;
    case NavigationOutcomeCode::kInvalidTarget:
      response->set_outcome(NavigateResponse::INVALID_TARGET);
      break;
    case NavigationOutcomeCode::kActionServerUnavailable:
      response->set_outcome(NavigateResponse::ACTION_SERVER_UNAVAILABLE);
      break;
    case NavigationOutcomeCode::kGoalRejected:
      response->set_outcome(NavigateResponse::GOAL_REJECTED);
      break;
    case NavigationOutcomeCode::kAborted:
      response->set_outcome(NavigateResponse::ABORTED);
      break;
    case NavigationOutcomeCode::kTimeout:
      response->set_outcome(NavigateResponse::TIMEOUT);
      break;
    case NavigationOutcomeCode::kInternalError:
      response->set_outcome(NavigateResponse::INTERNAL_ERROR);
      break;
  }
  return grpc::Status::OK;
}

}  // namespace ros2_sdk::skeleton
