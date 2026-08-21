#ifndef ROS2_SDK__NAVIGATION_SERVICE_HPP_
#define ROS2_SDK__NAVIGATION_SERVICE_HPP_

#include <grpcpp/grpcpp.h>

#include <memory>

#include "navigation_smoke.grpc.pb.h"
#include "navigation_task_manager.hpp"

namespace ros2_sdk::skeleton {

class NavigationService final : public ros2_sdk::api::NavigationRpc::Service {
public:
  explicit NavigationService(std::shared_ptr<NavigationTaskManager> task_manager);

  grpc::Status Health(grpc::ServerContext* context, const ros2_sdk::api::HealthRequest* request,
                      ros2_sdk::api::HealthResponse* response) override;
  grpc::Status StartNavigation(grpc::ServerContext* context,
                               const ros2_sdk::api::StartNavigationRequest* request,
                               ros2_sdk::api::StartNavigationResponse* response) override;
  grpc::Status GetNavigation(grpc::ServerContext* context,
                             const ros2_sdk::api::GetNavigationRequest* request,
                             ros2_sdk::api::GetNavigationResponse* response) override;
  grpc::Status CancelNavigation(grpc::ServerContext* context,
                                const ros2_sdk::api::CancelNavigationRequest* request,
                                ros2_sdk::api::CancelNavigationResponse* response) override;
  grpc::Status WatchNavigation(grpc::ServerContext* context,
                               const ros2_sdk::api::WatchNavigationRequest* request,
                               grpc::ServerWriter<ros2_sdk::api::NavigationEvent>* writer) override;

private:
  static void fill_task(const NavigationTask& task, ros2_sdk::api::NavigationTask* proto_task);
  static bool is_terminal(const NavigationTask& task);

  std::shared_ptr<NavigationTaskManager> task_manager_;
};

}  // namespace ros2_sdk::skeleton

#endif  // ROS2_SDK__NAVIGATION_SERVICE_HPP_
