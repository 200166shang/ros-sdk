#ifndef ROS2_SDK__LOG_EVENT_HPP_
#define ROS2_SDK__LOG_EVENT_HPP_

#include <chrono>
#include <cstdint>
#include <optional>
#include <ros2_sdk/error.hpp>
#include <ros2_sdk/log_field.hpp>
#include <ros2_sdk/log_level.hpp>
#include <string>

namespace ros2_sdk {

// SourceLocation carries optional source information without requiring C++20 source_location.
struct SourceLocation {
  const char* file = "";
  std::uint32_t line = 0;
  const char* function = "";
};

// LogEvent is the backend-neutral representation of one log record.
struct LogEvent {
  std::chrono::system_clock::time_point timestamp = std::chrono::system_clock::now();
  LogLevel level = LogLevel::kInfo;
  std::string module;
  std::string event;
  std::string message;
  std::uint64_t thread_id = 0;
  SourceLocation source;
  LogFields fields;
  std::optional<Error> error;

  // render_text returns the compact representation used by console and ROS sinks.
  std::string render_text() const;
};

}  // namespace ros2_sdk

#endif  // ROS2_SDK__LOG_EVENT_HPP_
