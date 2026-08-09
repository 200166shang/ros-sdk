#include <memory>
#include <rcl_interfaces/msg/log.hpp>
#include <rclcpp/logging.hpp>
#include <rclcpp/qos.hpp>
#include <ros2_sdk/logger.hpp>
#include <ros2_sdk/ros_logger.hpp>
#include <string>

namespace ros2_sdk {

Result<void> RosLogger::initialize(LoggerConfig config, const rclcpp::Logger& logger) {
  if (!rclcpp::ok() || logger.get_name() == nullptr) {
    return Result<void>::failure(
        Error(ErrorCode::kNotInitialized, "ROS logging requires an initialized named logger"));
  }

  const rclcpp::Logger ros_logger = logger;
  config.rosout.enabled = true;
  config.rosout_callback = [ros_logger](LogLevel level, std::string_view message) {
    const std::string text(message);
    switch (level) {
      case LogLevel::kDebug:
        RCLCPP_DEBUG(ros_logger, "%s", text.c_str());
        break;
      case LogLevel::kInfo:
        RCLCPP_INFO(ros_logger, "%s", text.c_str());
        break;
      case LogLevel::kWarn:
        RCLCPP_WARN(ros_logger, "%s", text.c_str());
        break;
      case LogLevel::kError:
        RCLCPP_ERROR(ros_logger, "%s", text.c_str());
        break;
      case LogLevel::kFatal:
        RCLCPP_FATAL(ros_logger, "%s", text.c_str());
        break;
      case LogLevel::kOff:
        break;
    }
  };
  return Logger::initialize(config);
}

Result<void> RosLogger::initialize(LoggerConfig config, const rclcpp::Node::SharedPtr& node) {
  if (!rclcpp::ok() || node == nullptr) {
    return Result<void>::failure(
        Error(ErrorCode::kNotInitialized, "ROS logging requires an initialized node"));
  }

  const auto publisher =
      node->create_publisher<rcl_interfaces::msg::Log>("/rosout", rclcpp::RosoutQoS());
  const auto clock = node->get_clock();
  const std::string logger_name =
      node->get_logger().get_name() == nullptr ? "ros2_sdk" : node->get_logger().get_name();
  config.rosout.enabled = true;
  config.rosout_callback = [publisher, clock, logger_name](LogLevel level,
                                                           std::string_view message) {
    rcl_interfaces::msg::Log record;
    record.stamp = clock->now();
    record.level = static_cast<std::uint8_t>(10U + (10U * log_level_value(level)));
    record.name = logger_name;
    record.msg = message;
    publisher->publish(record);
  };
  return Logger::initialize(config);
}

}  // namespace ros2_sdk
