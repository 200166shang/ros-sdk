#include <grpcpp/grpcpp.h>
#include <pthread.h>
#include <signal.h>

#include <chrono>
#include <csignal>
#include <cstdlib>
#include <iostream>
#include <memory>
#include <rclcpp/rclcpp.hpp>
#include <string>
#include <thread>

#include "delivery_service.hpp"
#include "runtime_health_service.hpp"

namespace {

constexpr char kDefaultAddress[] = "0.0.0.0:8765";

std::string server_address(int argc, char* argv[]) {
  if (argc > 1) {
    return argv[1];
  }

  if (const char* configured_address = std::getenv("ROS2_SDK_GRPC_ADDRESS");
      configured_address != nullptr && configured_address[0] != '\0') {
    return configured_address;
  }

  return kDefaultAddress;
}

}  // namespace

int main(int argc, char* argv[]) {
  sigset_t signals;
  sigemptyset(&signals);
  sigaddset(&signals, SIGINT);
  sigaddset(&signals, SIGTERM);
  if (pthread_sigmask(SIG_BLOCK, &signals, nullptr) != 0) {
    std::cerr << "failed to block shutdown signals\n";
    return 1;
  }

  const std::string address = server_address(argc, argv);
  int ros_argc = 0;
  char** ros_argv = nullptr;
  rclcpp::init(ros_argc, ros_argv);
  auto node = std::make_shared<rclcpp::Node>("rosbridge_runtime");
  auto delivery_service = std::make_shared<ros2_sdk::DeliveryService>(node);
  ros2_sdk::RuntimeHealthService health_service(
      [delivery_service] { return delivery_service->ready(std::chrono::milliseconds(0)); });
  grpc::ServerBuilder builder;
  builder.AddListeningPort(address, grpc::InsecureServerCredentials());
  builder.RegisterService(&health_service);
  builder.RegisterService(delivery_service.get());
  std::unique_ptr<grpc::Server> server = builder.BuildAndStart();
  if (server == nullptr) {
    std::cerr << "failed to start Runtime gRPC server on " << address << '\n';
    return 1;
  }

  std::cout << "Runtime gRPC server listening on " << address << '\n';

  rclcpp::executors::SingleThreadedExecutor executor;
  executor.add_node(node);
  std::thread ros_thread([&executor] { executor.spin(); });

  std::thread shutdown_thread([&server, &signals] {
    int signal_number = 0;
    if (sigwait(&signals, &signal_number) == 0) {
      server->Shutdown();
      rclcpp::shutdown();
    }
  });

  server->Wait();
  shutdown_thread.join();
  ros_thread.join();
  return 0;
}
