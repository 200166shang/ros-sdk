#include <gtest/gtest.h>

#include <chrono>
#include <memory>
#include <rcl_interfaces/msg/log.hpp>
#include <rclcpp/rclcpp.hpp>
#include <ros2_sdk/logger.hpp>
#include <ros2_sdk/logger_config.hpp>
#include <ros2_sdk/ros_logger.hpp>
#include <string>
#include <thread>

namespace ros2_sdk {
namespace {

TEST(RosLoggerTest, PublishesHumanReadableEventsToRosout) {
  int argc = 0;
  char** argv = nullptr;
  rclcpp::init(argc, argv);

  const auto node = std::make_shared<rclcpp::Node>("ros2_sdk_logger_test");
  std::string received_message;
  std::size_t received_count = 0U;
  auto subscription = node->create_subscription<rcl_interfaces::msg::Log>(
      "/rosout", rclcpp::RosoutQoS(),
      [&received_message,
       &received_count](const rcl_interfaces::msg::Log::ConstSharedPtr& message) {
        ++received_count;
        if (message->msg.find("adapter is ready") != std::string::npos) {
          received_message = message->msg;
        }
      });

  LoggerConfig config = LoggerConfig::defaults();
  config.console.enabled = false;
  config.file.enabled = false;
  config.rosout.enabled = true;
  ASSERT_TRUE(RosLogger::initialize(config, node));
  EXPECT_GT(node->count_subscribers("/rosout"), 0U);

  rclcpp::executors::SingleThreadedExecutor executor;
  executor.add_node(node);
  const auto discovery_deadline = std::chrono::steady_clock::now() + std::chrono::seconds(2);
  while (node->count_publishers("/rosout") == 0U &&
         std::chrono::steady_clock::now() < discovery_deadline) {
    executor.spin_some();
    std::this_thread::sleep_for(std::chrono::milliseconds(10));
  }

  Logger::get("rosbridge.ros_adapter").log(LogLevel::kInfo, "adapter_ready", "adapter is ready");
  Logger::flush();

  const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(3);
  while (received_message.empty() && std::chrono::steady_clock::now() < deadline) {
    executor.spin_some();
    std::this_thread::sleep_for(std::chrono::milliseconds(10));
  }

  EXPECT_EQ(received_message, "INFO [rosbridge.ros_adapter] adapter_ready: adapter is ready");
  EXPECT_GT(received_count, 0U);
  Logger::shutdown();
  executor.remove_node(node);
  rclcpp::shutdown();
}

}  // namespace
}  // namespace ros2_sdk
