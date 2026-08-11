#ifndef ROS2_SDK__LOGGING__LOG_HPP_
#define ROS2_SDK__LOGGING__LOG_HPP_

#include <fmt/format.h>

#include <chrono>
#include <cstdint>
#include <functional>
#include <ros2_sdk/logging/level.hpp>
#include <string>

namespace ros2_sdk::log {

/// SourceLocation identifies the producer call site.
struct SourceLocation {
  const char* file = "";
  std::uint32_t line = 0U;
  const char* function = "";
};

/// LogMessage is the backend-neutral representation delivered to a callback.
struct LogMessage {
  std::chrono::system_clock::time_point time;
  Level level = Level::kInfo;
  std::string module;
  std::string message;
  std::string file;
  std::string function;
  std::uint32_t line = 0U;
  std::uint64_t thread_id = 0U;
};

/// LogCallback receives a message from a logging worker thread.
using LogCallback = std::function<void(const LogMessage&)>;

/// LogStats exposes queue overflow and sink isolation counters.
struct LogStats {
  std::uint64_t dropped_count = 0U;
  std::uint64_t sink_error_count = 0U;
  std::uint64_t callback_error_count = 0U;
};

/// Redacted formats as [REDACTED] without retaining the source value.
class Redacted final {};

/// redact wraps a sensitive value for safe formatting.
template <typename T>
Redacted redact(const T&) noexcept {
  return {};
}

}  // namespace ros2_sdk::log

template <>
struct fmt::formatter<ros2_sdk::log::Redacted> {
  constexpr auto parse(fmt::format_parse_context& context) { return context.begin(); }

  template <typename FormatContext>
  auto format(const ros2_sdk::log::Redacted&, FormatContext& context) const {
    return fmt::format_to(context.out(), "[REDACTED]");
  }
};

#endif  // ROS2_SDK__LOGGING__LOG_HPP_
