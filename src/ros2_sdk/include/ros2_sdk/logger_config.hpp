#ifndef ROS2_SDK__LOGGER_CONFIG_HPP_
#define ROS2_SDK__LOGGER_CONFIG_HPP_

#include <cstddef>
#include <filesystem>
#include <functional>
#include <map>
#include <ros2_sdk/log_level.hpp>
#include <ros2_sdk/result.hpp>
#include <string>
#include <string_view>

namespace ros2_sdk {

using RosoutCallback = std::function<void(LogLevel, std::string_view)>;

struct SinkConfig {
  bool enabled = true;
  LogLevel level = LogLevel::kInfo;
};

struct FileSinkConfig {
  bool enabled = true;
  LogLevel level = LogLevel::kDebug;
  std::filesystem::path directory = "logs";
  std::string name = "rosbridge.jsonl";
  std::size_t max_size = 10U * 1024U * 1024U;
  std::size_t max_files = 5U;
};

// LoggerConfig contains startup settings. Runtime ROS service reconfiguration is not included.
struct LoggerConfig {
  static LoggerConfig defaults();

  LogLevel global_level = LogLevel::kInfo;
  std::map<std::string, LogLevel> module_levels;
  SinkConfig console;
  FileSinkConfig file;
  SinkConfig rosout{false, LogLevel::kInfo};
  RosoutCallback rosout_callback;
  std::size_t normal_queue_size = 8192U;
  std::size_t critical_queue_size = 256U;
  bool flush_on_error = true;
  bool flush_on_fatal = true;

  // effective_level resolves the longest matching dot-separated module prefix.
  LogLevel effective_level(std::string_view module) const noexcept;

  // from_file loads a JSON configuration file and leaves unspecified values at defaults.
  static Result<LoggerConfig> from_file(const std::filesystem::path& path);

  // apply_environment applies ROS2_SDK_LOG_* overrides to this configuration.
  Result<void> apply_environment();

  // apply_command_line applies supported --log-* overrides to this configuration.
  Result<void> apply_command_line(int argc, const char* const argv[]);
};

}  // namespace ros2_sdk

#endif  // ROS2_SDK__LOGGER_CONFIG_HPP_
