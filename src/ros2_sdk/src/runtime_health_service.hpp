#ifndef ROS2_SDK__RUNTIME_HEALTH_SERVICE_HPP_
#define ROS2_SDK__RUNTIME_HEALTH_SERVICE_HPP_

#include <grpcpp/support/status.h>

#include <functional>

#include "runtime_health.grpc.pb.h"

namespace ros2_sdk {

/**
 * Implements the Runtime health contract exposed to external clients.
 *
 * The service reports process liveness independently from delivery readiness.
 * Delivery readiness reflects whether the runtime can currently reach Nav2.
 */
class RuntimeHealthService final : public runtime::RuntimeService::Service {
public:
  using ReadinessProvider = std::function<bool()>;

  explicit RuntimeHealthService(ReadinessProvider readiness_provider = {});

  /** Return the current liveness and delivery readiness state. */
  grpc::Status Health(grpc::ServerContext* context, const runtime::HealthRequest* request,
                      runtime::HealthResponse* response) override;

private:
  ReadinessProvider readiness_provider_;
};

}  // namespace ros2_sdk

#endif  // ROS2_SDK__RUNTIME_HEALTH_SERVICE_HPP_
