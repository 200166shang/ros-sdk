#ifndef ROS2_SDK__LOGGING__LEVEL_HPP_
#define ROS2_SDK__LOGGING__LEVEL_HPP_

#include <cstdint>
#include <string_view>

namespace ros2_sdk::log {

/// Level is ordered from the least to the most severe message.
enum class Level : std::uint8_t {
  kTrace = 0,
  kDebug = 1,
  kInfo = 2,
  kWarn = 3,
  kError = 4,
  kCritical = 5,
  kOff = 6,
};

/// level_value returns the stable numeric value used for severity comparisons.
constexpr std::uint8_t level_value(Level level) noexcept {
  return static_cast<std::uint8_t>(level);
}

/// level_name returns the stable uppercase name used by text sinks.
constexpr std::string_view level_name(Level level) noexcept {
  switch (level) {
    case Level::kTrace:
      return "TRACE";
    case Level::kDebug:
      return "DEBUG";
    case Level::kInfo:
      return "INFO";
    case Level::kWarn:
      return "WARN";
    case Level::kError:
      return "ERROR";
    case Level::kCritical:
      return "CRITICAL";
    case Level::kOff:
      return "OFF";
  }
  return "OFF";
}

/// level_enabled reports whether message_level passes minimum_level.
constexpr bool level_enabled(Level message_level, Level minimum_level) noexcept {
  return message_level != Level::kOff && message_level >= minimum_level;
}

}  // namespace ros2_sdk::log

#endif  // ROS2_SDK__LOGGING__LEVEL_HPP_
