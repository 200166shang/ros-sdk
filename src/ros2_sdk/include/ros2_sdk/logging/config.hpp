#ifndef ROS2_SDK__LOGGING__CONFIG_HPP_
#define ROS2_SDK__LOGGING__CONFIG_HPP_

#include <cstddef>
#include <functional>
#include <optional>
#include <ros2_sdk/logging/level.hpp>
#include <ros2_sdk/logging/log.hpp>
#include <string>

namespace ros2_sdk::log {

struct RotatingFileConfig {
  /// path is the primary log file path.
  std::string path;
  /// max_size_bytes is the maximum size of one file before rotation.
  std::size_t max_size_bytes = 10U * 1024U * 1024U;
  /// max_files is the number of files retained by the rotating sink.
  std::size_t max_files = 5U;
};

/// LogConfig contains startup settings for the portable logging core.
struct LogConfig {
  /// global_level is the default minimum level for all modules.
  Level global_level = Level::kInfo;
  /// queue_size bounds the shared asynchronous queue.
  std::size_t queue_size = 8192U;
  /// worker_threads controls the number of private spdlog workers.
  std::size_t worker_threads = 1U;
  /// console_enabled enables the human-readable console sink.
  bool console_enabled = true;
  /// file enables a rotating text file when present.
  std::optional<RotatingFileConfig> file;
  /// callback receives events on a logging worker thread when present.
  LogCallback callback;
};

}  // namespace ros2_sdk::log

#endif  // ROS2_SDK__LOGGING__CONFIG_HPP_
