#ifndef ROS2_SDK__ERROR_HPP_
#define ROS2_SDK__ERROR_HPP_

#include <cstdint>
#include <string>
#include <string_view>
#include <utility>

namespace ros2_sdk {

/**
 * @brief Stable machine-readable result and error identifiers.
 *
 * Numeric values are part of the public API. Once published, a value must not
 * be reused for a different meaning.
 */
enum class ErrorCode : std::uint32_t {  // NOLINT(performance-enum-size)
  kOk = 0,
  kUnknown = 1,

  // 1000-1999: Core.
  kInvalidArgument = 1001,
  kNotInitialized = 1002,

  // 2000-2999: Communication.
  kCommunicationTimeout = 2001,
  kServiceUnavailable = 2002,

  // 3000-3999: Lifecycle.
  kModuleStartFailed = 3001,
};

/**
 * @brief Returns the stable numeric value of an error code.
 */
constexpr std::uint32_t error_code_value(ErrorCode code) noexcept {
  return static_cast<std::uint32_t>(code);
}

/**
 * @brief Returns whether an error code represents success.
 */
constexpr bool is_success(ErrorCode code) noexcept {
  return code == ErrorCode::kOk;
}

/**
 * @brief Returns the stable display name of an error code.
 *
 * Unknown numeric values are preserved by ErrorCode and are represented by
 * "UNKNOWN" when converted to a name.
 */
constexpr std::string_view error_code_name(ErrorCode code) noexcept {
  switch (code) {
    case ErrorCode::kOk:
      return "OK";
    case ErrorCode::kUnknown:
      return "UNKNOWN";
    case ErrorCode::kInvalidArgument:
      return "INVALID_ARGUMENT";
    case ErrorCode::kNotInitialized:
      return "NOT_INITIALIZED";
    case ErrorCode::kCommunicationTimeout:
      return "COMMUNICATION_TIMEOUT";
    case ErrorCode::kServiceUnavailable:
      return "SERVICE_UNAVAILABLE";
    case ErrorCode::kModuleStartFailed:
      return "MODULE_START_FAILED";
    default:
      return "UNKNOWN";
  }
}

/**
 * @brief A value object containing an error code and human-readable detail.
 *
 * Error is intended for normal, non-real-time paths. It owns its message so
 * that the error can safely outlive the operation that produced it.
 */
class Error {
public:
  /**
   * @brief Constructs an error with its code and explanatory message.
   */
  Error(ErrorCode code, std::string message) : code_(code), message_(std::move(message)) {}

  /**
   * @brief Returns the machine-readable error code.
   */
  ErrorCode code() const noexcept { return code_; }

  /**
   * @brief Returns the human-readable error message.
   */
  const std::string& message() const noexcept { return message_; }

  /**
   * @brief Returns a stable human-readable representation.
   */
  std::string to_string() const {
    std::string result(error_code_name(code_));
    if (!message_.empty()) {
      result += ": ";
      result += message_;
    }
    return result;
  }

private:
  ErrorCode code_;
  std::string message_;
};

}  // namespace ros2_sdk

#endif  // ROS2_SDK__ERROR_HPP_
