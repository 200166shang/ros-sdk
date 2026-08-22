#include "runtime_health_service.hpp"

namespace ros2_sdk {

grpc::Status RuntimeHealthService::Health(grpc::ServerContext* /*context*/,
                                          const runtime::HealthRequest* /*request*/,
                                          runtime::HealthResponse* response) {
  response->set_alive(true);
  response->set_delivery_ready(false);
  response->set_readiness_reason("delivery capability is not available yet");
  return grpc::Status::OK;
}

}  // namespace ros2_sdk
