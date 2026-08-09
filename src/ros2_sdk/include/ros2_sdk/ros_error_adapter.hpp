#ifndef ROS2_SDK__ROS_ERROR_ADAPTER_HPP_
#define ROS2_SDK__ROS_ERROR_ADAPTER_HPP_

#include <rclcpp/exceptions/exceptions.hpp>
#include <ros2_sdk/error.hpp>
#include <string>
#include <utility>

namespace ros2_sdk {

// error_code_from_rcl maps a ROS 2 return code to the RosBridge error model.
constexpr ErrorCode error_code_from_rcl(rcl_ret_t ret) noexcept {
  switch (ret) {
    case RCL_RET_OK:
      return ErrorCode::kOk;
    case RCL_RET_INVALID_ARGUMENT:
      return ErrorCode::kInvalidArgument;
    case RCL_RET_NOT_INIT:
      return ErrorCode::kNotInitialized;
    case RCL_RET_TIMEOUT:
      return ErrorCode::kCommunicationTimeout;
    default:
      return ErrorCode::kUnknown;
  }
}

// error_from_rcl converts a ROS 2 return code and message to an Error.
inline Error error_from_rcl(rcl_ret_t ret, std::string message) {
  return Error(error_code_from_rcl(ret), std::move(message));
}

// error_from_rcl converts an rclcpp exception to an Error.
inline Error error_from_rcl(const rclcpp::exceptions::RCLErrorBase& error) {
  return Error(error_code_from_rcl(error.ret), error.message);
}

}  // namespace ros2_sdk

#endif  // ROS2_SDK__ROS_ERROR_ADAPTER_HPP_
