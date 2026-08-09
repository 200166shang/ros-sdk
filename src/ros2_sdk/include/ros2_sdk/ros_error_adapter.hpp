#ifndef ROS2_SDK__ROS_ERROR_ADAPTER_HPP_
#define ROS2_SDK__ROS_ERROR_ADAPTER_HPP_

#include <rclcpp/exceptions/exceptions.hpp>
#include <ros2_sdk/error.hpp>
#include <string>
#include <utility>

namespace ros2_sdk {

/**
 * @brief Converts a common ROS 2 return code to the RosBridge error model.
 *
 * Return codes not represented by the initial RosBridge catalog map to
 * ErrorCode::kUnknown while preserving the original ROS return code at the
 * call site if it is needed for lower-level diagnostics.
 */
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

/**
 * @brief Converts a ROS 2 return code and message to an Error.
 */
inline Error error_from_rcl(rcl_ret_t ret, std::string message) {
  return Error(error_code_from_rcl(ret), std::move(message));
}

/**
 * @brief Converts an rclcpp exception's code and message to an Error.
 */
inline Error error_from_rcl(const rclcpp::exceptions::RCLErrorBase& error) {
  return Error(error_code_from_rcl(error.ret), error.message);
}

}  // namespace ros2_sdk

#endif  // ROS2_SDK__ROS_ERROR_ADAPTER_HPP_
