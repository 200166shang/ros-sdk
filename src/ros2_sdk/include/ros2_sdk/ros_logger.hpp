#ifndef ROS2_SDK__ROS_LOGGER_HPP_
#define ROS2_SDK__ROS_LOGGER_HPP_

#include <rclcpp/logger.hpp>
#include <rclcpp/node.hpp>
#include <ros2_sdk/logger_config.hpp>
#include <ros2_sdk/result.hpp>

namespace ros2_sdk {

// RosLogger installs the native ROS 2 logging path as the core logger's optional rosout sink.
class RosLogger {
public:
  // initialize requires rclcpp to be initialized and uses the supplied logger name for /rosout.
  static Result<void> initialize(LoggerConfig config, const rclcpp::Logger& logger);

  // initialize publishes directly to /rosout using the node's ROS-native QoS profile.
  static Result<void> initialize(LoggerConfig config, const rclcpp::Node::SharedPtr& node);
};

}  // namespace ros2_sdk

#endif  // ROS2_SDK__ROS_LOGGER_HPP_
