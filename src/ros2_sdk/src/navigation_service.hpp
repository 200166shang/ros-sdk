#ifndef ROS2_SDK__NAVIGATION_SERVICE_HPP_
#define ROS2_SDK__NAVIGATION_SERVICE_HPP_

#include <grpcpp/grpcpp.h>

#include <memory>

#include "navigation_action_client.hpp"
#include "navigation_smoke.grpc.pb.h"

namespace ros2_sdk::skeleton {

class NavigationService final : public NavigationRpc::Service {
public:
  explicit NavigationService(std::shared_ptr<NavigationActionClient> action_client);

  grpc::Status Health(grpc::ServerContext* context, const HealthRequest* request,
                      HealthResponse* response) override;
  grpc::Status Navigate(grpc::ServerContext* context, const NavigateRequest* request,
                        NavigateResponse* response) override;

private:
  std::shared_ptr<NavigationActionClient> action_client_;
};

}  // namespace ros2_sdk::skeleton

#endif  // ROS2_SDK__NAVIGATION_SERVICE_HPP_
