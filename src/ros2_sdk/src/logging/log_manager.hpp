#ifndef ROS2_SDK__LOGGING__LOG_MANAGER_HPP_
#define ROS2_SDK__LOGGING__LOG_MANAGER_HPP_

#include <atomic>
#include <map>
#include <memory>
#include <mutex>
#include <ros2_sdk/logging/config.hpp>
#include <ros2_sdk/logging/logger.hpp>
#include <shared_mutex>
#include <string>
#include <string_view>
#include <vector>

#include "spdlog_backend.hpp"

namespace ros2_sdk::log::detail {

class LogManager final {
public:
  explicit LogManager(LogConfig config);
  ~LogManager();

  Result<void> start();
  void shutdown() noexcept;
  void flush() noexcept;

  bool should_log(std::string_view module, Level level) const noexcept;
  std::shared_ptr<ModuleLogger> get_module_logger(const std::string& module);
  void submit(const std::shared_ptr<ModuleLogger>& module_logger, std::string_view module,
              Level level, SourceLocation source, std::string_view message) noexcept;

  Result<void> set_global_level(Level level);
  Result<void> set_module_level(std::string module_prefix, Level level);
  Result<void> clear_module_level(std::string_view module_prefix);
  LogStats stats() const noexcept;

private:
  bool should_log_unlocked(std::string_view module, Level level) const noexcept;

  LogConfig config_;
  std::shared_ptr<SpdlogBackend> backend_;
  mutable std::shared_mutex lifecycle_mutex_;
  mutable std::mutex modules_mutex_;
  std::map<std::string, Level> module_levels_;
  std::map<std::string, std::shared_ptr<ModuleLogger>> modules_;
  bool accepting_ = false;
};

}  // namespace ros2_sdk::log::detail

#endif  // ROS2_SDK__LOGGING__LOG_MANAGER_HPP_
