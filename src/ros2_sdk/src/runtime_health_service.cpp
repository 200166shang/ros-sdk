#include "runtime_health_service.hpp"

#include <utility>

namespace ros2_sdk {

RuntimeHealthService::RuntimeHealthService(ReadinessProvider readiness_provider)
    : readiness_provider_(std::move(readiness_provider)) {}

grpc::Status RuntimeHealthService::Health(grpc::ServerContext* /*context*/,
                                          const runtime::HealthRequest* /*request*/,
                                          runtime::HealthResponse* response) {
  response->set_alive(true);
  const bool delivery_ready = readiness_provider_ != nullptr && readiness_provider_();
  response->set_delivery_ready(delivery_ready);
  response->set_readiness_reason(delivery_ready ? "delivery capability is ready"
                                                : "delivery capability is not available yet");
  return grpc::Status::OK;
}

}  // namespace ros2_sdk
