#ifndef ROS2_SDK__LOGGING__LOGGER_HPP_
#define ROS2_SDK__LOGGING__LOGGER_HPP_

#include <fmt/format.h>

#include <atomic>
#include <chrono>
#include <memory>
#include <mutex>
#include <ros2_sdk/logging/config.hpp>
#include <ros2_sdk/logging/log.hpp>
#include <ros2_sdk/result.hpp>
#include <stdexcept>
#include <string>
#include <string_view>

namespace ros2_sdk::log::detail {
class LogManager;
struct ModuleLogger;
}  // namespace ros2_sdk::log::detail

namespace ros2_sdk::log {

class Logger {
public:
  /// should_log checks the current global and module level before formatting.
  bool should_log(Level level) const noexcept;

  /// log submits an already formatted message without throwing.
  void log(Level level, SourceLocation source, std::string_view message) const noexcept;

  /// log formats arguments only after the current level accepts the message.
  template <typename... Args>
  void log(Level level, SourceLocation source, std::string_view format,
           Args&&... args) const noexcept {
    if (!should_log(level)) {
      return;
    }
    try {
      log(level, source, fmt::vformat(format, fmt::make_format_args(args...)));
    } catch (const std::exception&) {
      // Logging must not propagate formatting failures into the business path.
    }
  }

private:
  friend Logger get_logger(std::string module);

  Logger(std::shared_ptr<detail::LogManager> manager,
         std::shared_ptr<detail::ModuleLogger> module_logger, std::string module);

  std::shared_ptr<detail::LogManager> manager_;
  std::shared_ptr<detail::ModuleLogger> module_logger_;
  std::string module_;
};

/// initialize starts one process-local SDK logging backend.
Result<void> initialize(const LogConfig& config);
/// flush waits for accepted messages to reach all configured sinks.
void flush() noexcept;
/// shutdown stops admission, drains accepted messages, and releases the backend.
void shutdown() noexcept;

/// get_logger returns a module-bound lightweight logger handle.
Logger get_logger(std::string module);
/// set_global_level updates the default level for existing and future handles.
Result<void> set_global_level(Level level);
/// set_module_level updates the longest-prefix level rule.
Result<void> set_module_level(std::string module_prefix, Level level);
/// clear_module_level removes one module rule and restores inherited filtering.
Result<void> clear_module_level(std::string_view module_prefix);
/// stats returns current queue and sink counters.
LogStats stats() noexcept;

namespace detail {

struct ThrottleState {
  std::mutex mutex;
  std::chrono::steady_clock::time_point last;
  bool has_last = false;
};

inline bool throttle_acquire(ThrottleState& state, std::chrono::steady_clock::duration interval) {
  const auto now = std::chrono::steady_clock::now();
  std::lock_guard<std::mutex> lock(state.mutex);
  if (state.has_last && now - state.last < interval) {
    return false;
  }
  state.last = now;
  state.has_last = true;
  return true;
}

}  // namespace detail

}  // namespace ros2_sdk::log

#define ROS2_SDK_LOG_IMPL(logger_expression, level_value, source, ...)                             \
  do {                                                                                             \
    auto&& ros2_sdk_logger = (logger_expression);                                                  \
    if (ros2_sdk_logger.should_log(level_value)) {                                                 \
      ros2_sdk_logger.log(level_value, source, __VA_ARGS__);                                       \
    }                                                                                              \
  } while (false)

#define SDK_LOG_TRACE(logger, ...)                                                                 \
  ROS2_SDK_LOG_IMPL(logger, ::ros2_sdk::log::Level::kTrace,                                        \
                    ::ros2_sdk::log::SourceLocation{__FILE__, __LINE__, __func__}, __VA_ARGS__)

#define SDK_LOG_DEBUG(logger, ...)                                                                 \
  ROS2_SDK_LOG_IMPL(logger, ::ros2_sdk::log::Level::kDebug,                                        \
                    ::ros2_sdk::log::SourceLocation{__FILE__, __LINE__, __func__}, __VA_ARGS__)

#define SDK_LOG_INFO(logger, ...)                                                                  \
  ROS2_SDK_LOG_IMPL(logger, ::ros2_sdk::log::Level::kInfo,                                         \
                    ::ros2_sdk::log::SourceLocation{__FILE__, __LINE__, __func__}, __VA_ARGS__)

#define SDK_LOG_WARN(logger, ...)                                                                  \
  ROS2_SDK_LOG_IMPL(logger, ::ros2_sdk::log::Level::kWarn,                                         \
                    ::ros2_sdk::log::SourceLocation{__FILE__, __LINE__, __func__}, __VA_ARGS__)

#define SDK_LOG_ERROR(logger, ...)                                                                 \
  ROS2_SDK_LOG_IMPL(logger, ::ros2_sdk::log::Level::kError,                                        \
                    ::ros2_sdk::log::SourceLocation{__FILE__, __LINE__, __func__}, __VA_ARGS__)

#define SDK_LOG_CRITICAL(logger, ...)                                                              \
  ROS2_SDK_LOG_IMPL(logger, ::ros2_sdk::log::Level::kCritical,                                     \
                    ::ros2_sdk::log::SourceLocation{__FILE__, __LINE__, __func__}, __VA_ARGS__)

#define SDK_LOG_WARN_ONCE(logger, ...)                                                             \
  do {                                                                                             \
    auto&& ros2_sdk_logger = (logger);                                                             \
    static std::atomic_flag ros2_sdk_once = ATOMIC_FLAG_INIT;                                      \
    if (ros2_sdk_logger.should_log(::ros2_sdk::log::Level::kWarn) &&                               \
        !ros2_sdk_once.test_and_set(std::memory_order_acq_rel)) {                                  \
      ros2_sdk_logger.log(::ros2_sdk::log::Level::kWarn,                                           \
                          ::ros2_sdk::log::SourceLocation{__FILE__, __LINE__, __func__},           \
                          __VA_ARGS__);                                                            \
    }                                                                                              \
  } while (false)

#define SDK_LOG_WARN_THROTTLE(logger, interval, ...)                                               \
  do {                                                                                             \
    auto&& ros2_sdk_logger = (logger);                                                             \
    if (ros2_sdk_logger.should_log(::ros2_sdk::log::Level::kWarn)) {                               \
      const auto ros2_sdk_interval = (interval);                                                   \
      static ::ros2_sdk::log::detail::ThrottleState ros2_sdk_throttle;                             \
      if (::ros2_sdk::log::detail::throttle_acquire(ros2_sdk_throttle, ros2_sdk_interval)) {       \
        ros2_sdk_logger.log(::ros2_sdk::log::Level::kWarn,                                         \
                            ::ros2_sdk::log::SourceLocation{__FILE__, __LINE__, __func__},         \
                            __VA_ARGS__);                                                          \
      }                                                                                            \
    }                                                                                              \
  } while (false)

#endif  // ROS2_SDK__LOGGING__LOGGER_HPP_
