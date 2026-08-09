#ifndef ROS2_SDK__LOG_LEVEL_HPP_
#define ROS2_SDK__LOG_LEVEL_HPP_

#include <cstdint>
#include <optional>
#include <string_view>

namespace ros2_sdk {

// LogLevel follows the ROS-style severity order while keeping FATAL non-terminal.
enum class LogLevel : std::uint8_t {  // NOLINT(performance-enum-size)
  kDebug = 0,
  kInfo = 1,
  kWarn = 2,
  kError = 3,
  kFatal = 4,
  kOff = 5,
};

constexpr std::uint8_t log_level_value(LogLevel level) noexcept {
  return static_cast<std::uint8_t>(level);
}

constexpr std::string_view log_level_name(LogLevel level) noexcept {
  switch (level) {
    case LogLevel::kDebug:
      return "DEBUG";
    case LogLevel::kInfo:
      return "INFO";
    case LogLevel::kWarn:
      return "WARN";
    case LogLevel::kError:
      return "ERROR";
    case LogLevel::kFatal:
      return "FATAL";
    case LogLevel::kOff:
      return "OFF";
  }
  return "OFF";
}

inline std::optional<LogLevel> parse_log_level(std::string_view name) noexcept {
  if (name == "DEBUG") {
    return LogLevel::kDebug;
  }
  if (name == "INFO") {
    return LogLevel::kInfo;
  }
  if (name == "WARN" || name == "WARNING") {
    return LogLevel::kWarn;
  }
  if (name == "ERROR") {
    return LogLevel::kError;
  }
  if (name == "FATAL") {
    return LogLevel::kFatal;
  }
  if (name == "OFF") {
    return LogLevel::kOff;
  }
  return std::nullopt;
}

constexpr bool log_level_enabled(LogLevel message_level, LogLevel minimum_level) noexcept {
  return message_level != LogLevel::kOff && message_level >= minimum_level;
}

}  // namespace ros2_sdk

#endif  // ROS2_SDK__LOG_LEVEL_HPP_
