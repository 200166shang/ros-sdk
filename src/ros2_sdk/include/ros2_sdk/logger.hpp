#ifndef ROS2_SDK__LOGGER_HPP_
#define ROS2_SDK__LOGGER_HPP_

#include <cstdint>
#include <memory>
#include <ros2_sdk/log_event.hpp>
#include <ros2_sdk/logger_config.hpp>
#include <ros2_sdk/result.hpp>
#include <string>

namespace ros2_sdk::detail {
class LoggerBackend;
}

namespace ros2_sdk {

// Logger is a thread-safe, backend-neutral handle for one module namespace.
class Logger {
public:
  static Result<void> initialize(const LoggerConfig& config = LoggerConfig::defaults());

  static void shutdown() noexcept;

  static void flush() noexcept;

  static Logger get(std::string module);

  bool should_log(LogLevel level) const noexcept;

  void log(LogLevel level, std::string event, std::string message, LogFields fields = {},
           SourceLocation source = {}) const;

  void log(LogEvent event) const;

  void log_error(LogLevel level, std::string event, const Error& error, LogFields fields = {},
                 SourceLocation source = {}) const;

  std::uint64_t dropped_log_count() const noexcept;

  bool fallback_active() const noexcept;

private:
  Logger(std::shared_ptr<detail::LoggerBackend> backend, std::string module);

  std::shared_ptr<detail::LoggerBackend> backend_;
  std::string module_;
};

}  // namespace ros2_sdk

#endif  // ROS2_SDK__LOGGER_HPP_
