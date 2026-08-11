#ifndef ROS2_SDK__LOGGING__SPDLOG_BACKEND_HPP_
#define ROS2_SDK__LOGGING__SPDLOG_BACKEND_HPP_

#include <spdlog/async_logger.h>
#include <spdlog/details/thread_pool.h>

#include <atomic>
#include <condition_variable>
#include <cstdint>
#include <memory>
#include <mutex>
#include <ros2_sdk/logging/config.hpp>
#include <ros2_sdk/logging/log.hpp>
#include <ros2_sdk/result.hpp>
#include <string>
#include <vector>

namespace ros2_sdk::log::detail {

struct ModuleLogger {
  std::shared_ptr<spdlog::async_logger> logger;
};

class FlushCoordinator {
public:
  std::uint64_t target(std::size_t flushes);
  void complete();
  bool wait_for(std::uint64_t target);

private:
  std::mutex mutex_;
  std::condition_variable condition_;
  std::uint64_t completed_ = 0U;
};

class SpdlogBackend {
public:
  explicit SpdlogBackend(LogConfig config);
  ~SpdlogBackend();

  Result<void> start();
  void shutdown(const std::vector<std::shared_ptr<ModuleLogger>>& modules) noexcept;
  void flush(const std::vector<std::shared_ptr<ModuleLogger>>& modules) noexcept;

  std::shared_ptr<ModuleLogger> create_module_logger(const std::string& module);

  void submit(const std::shared_ptr<ModuleLogger>& module_logger, Level level,
              SourceLocation source, std::string_view message) noexcept;

  LogStats stats() const noexcept;

private:
  LogConfig config_;
  std::shared_ptr<spdlog::details::thread_pool> thread_pool_;
  std::shared_ptr<spdlog::sinks::sink> fanout_sink_;
  std::shared_ptr<FlushCoordinator> flush_coordinator_;
  std::atomic<bool> accepting_{false};
  std::atomic<std::uint64_t> sink_error_count_{0U};
  std::atomic<std::uint64_t> callback_error_count_{0U};
};

}  // namespace ros2_sdk::log::detail

#endif  // ROS2_SDK__LOGGING__SPDLOG_BACKEND_HPP_
