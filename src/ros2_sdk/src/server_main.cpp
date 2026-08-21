#include <grpcpp/grpcpp.h>

#include <iostream>
#include <memory>
#include <rclcpp/rclcpp.hpp>
#include <thread>

#include "nav2_navigation_adapter.hpp"
#include "navigation_service.hpp"

int main(int argc, char** argv) {
  rclcpp::init(argc, argv);

  auto node = std::make_shared<rclcpp::Node>("ros2_sdk_server");
  auto task_manager = std::make_shared<ros2_sdk::skeleton::NavigationTaskManager>();
  const std::weak_ptr<ros2_sdk::skeleton::NavigationTaskManager> weak_task_manager = task_manager;
  auto navigation_adapter = std::make_shared<ros2_sdk::skeleton::Nav2NavigationAdapter>(
      node, [weak_task_manager](const ros2_sdk::skeleton::NavigationAdapterEvent& event) {
        if (const auto manager = weak_task_manager.lock()) {
          manager->handle_adapter_event(event);
        }
      });
  task_manager->set_adapter(navigation_adapter);
  ros2_sdk::skeleton::NavigationService service(task_manager);

  grpc::ServerBuilder builder;
  int selected_port = 0;
  builder.AddListeningPort("0.0.0.0:8765", grpc::InsecureServerCredentials(), &selected_port);
  builder.RegisterService(&service);
  const std::unique_ptr<grpc::Server> server = builder.BuildAndStart();
  if (server == nullptr || selected_port != 8765) {
    std::cerr << "failed to start gRPC server on port 8765\n";
    rclcpp::shutdown();
    return 1;
  }

  std::cout << "ros2_sdk_server listening on 0.0.0.0:8765\n" << std::flush;

  rclcpp::executors::SingleThreadedExecutor executor;
  executor.add_node(node);
  std::thread grpc_thread([&server] { server->Wait(); });
  executor.spin();

  server->Shutdown();
  grpc_thread.join();
  executor.remove_node(node);
  rclcpp::shutdown();
  return 0;
}
