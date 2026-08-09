#ifndef ROS2_SDK__ERROR_HPP_
#define ROS2_SDK__ERROR_HPP_

#include <cstdint>
#include <string>
#include <string_view>
#include <utility>

namespace ros2_sdk {

// ErrorCode provides stable machine-readable result and error identifiers.
enum class ErrorCode : std::uint32_t {  // NOLINT(performance-enum-size)
  kOk = 0,
  kUnknown = 1,

  // ErrorCode Core range.
  kInvalidArgument = 1001,
  kNotInitialized = 1002,

  // ErrorCode Communication range.
  kCommunicationTimeout = 2001,
  kServiceUnavailable = 2002,

  // ErrorCode Lifecycle range.
  kModuleStartFailed = 3001,
};

// error_code_value returns the stable numeric value of an error code.
constexpr std::uint32_t error_code_value(ErrorCode code) noexcept {
  return static_cast<std::uint32_t>(code);
}

// is_success reports whether an error code represents success.
constexpr bool is_success(ErrorCode code) noexcept {
  return code == ErrorCode::kOk;
}

// error_code_name returns the stable display name of an error code.
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

// Error stores an error code and human-readable detail for normal paths.
class Error {
public:
  Error(ErrorCode code, std::string message) : code_(code), message_(std::move(message)) {}

  ErrorCode code() const noexcept { return code_; }

  const std::string& message() const noexcept { return message_; }

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
