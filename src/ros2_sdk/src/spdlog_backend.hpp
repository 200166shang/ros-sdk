#ifndef ROS2_SDK__DETAIL__SPDLOG_BACKEND_HPP_
#define ROS2_SDK__DETAIL__SPDLOG_BACKEND_HPP_

#include <cstdint>
#include <memory>
#include <ros2_sdk/log_event.hpp>
#include <ros2_sdk/logger_config.hpp>
#include <ros2_sdk/result.hpp>
#include <string_view>

namespace ros2_sdk::detail {

class LoggerBackend {
public:
  explicit LoggerBackend(LoggerConfig config);
  ~LoggerBackend();

  LoggerBackend(const LoggerBackend&) = delete;
  LoggerBackend& operator=(const LoggerBackend&) = delete;

  Result<void> start();
  void shutdown() noexcept;
  void flush() noexcept;

  bool should_log(std::string_view module, LogLevel level) const noexcept;
  void emit(const LogEvent& event) noexcept;
  std::uint64_t dropped_log_count() const noexcept;
  bool fallback_active() const noexcept;

private:
  class Impl;
  std::unique_ptr<Impl> impl_;
};

Result<std::shared_ptr<LoggerBackend>> make_logger_backend(const LoggerConfig& config);

}  // namespace ros2_sdk::detail

#endif  // ROS2_SDK__DETAIL__SPDLOG_BACKEND_HPP_
