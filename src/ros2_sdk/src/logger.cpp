#include <mutex>
#include <ros2_sdk/logger.hpp>
#include <thread>
#include <utility>

#include "spdlog_backend.hpp"

namespace ros2_sdk {
namespace {

std::mutex& backend_mutex() {
  static std::mutex mutex;
  return mutex;
}

std::shared_ptr<detail::LoggerBackend>& current_backend() {
  static std::shared_ptr<detail::LoggerBackend> backend;
  return backend;
}

}  // namespace

Logger::Logger(std::shared_ptr<detail::LoggerBackend> backend, std::string module)
    : backend_(std::move(backend)), module_(std::move(module)) {}

Result<void> Logger::initialize(const LoggerConfig& config) {
  LoggerConfig effective_config = config;
  auto environment_result = effective_config.apply_environment();
  if (!environment_result) {
    return environment_result;
  }

  const auto backend_result = detail::make_logger_backend(effective_config);
  if (!backend_result) {
    return Result<void>::failure(backend_result.error());
  }

  std::lock_guard<std::mutex> lock(backend_mutex());
  if (current_backend() != nullptr) {
    backend_result.value()->shutdown();
    return Result<void>::failure(
        Error(ErrorCode::kInvalidArgument, "logging has already been initialized"));
  }
  current_backend() = backend_result.value();
  return Result<void>::success();
}

void Logger::shutdown() noexcept {
  std::shared_ptr<detail::LoggerBackend> backend;
  {
    std::lock_guard<std::mutex> lock(backend_mutex());
    backend = std::move(current_backend());
  }
  if (backend != nullptr) {
    backend->shutdown();
  }
}

void Logger::flush() noexcept {
  std::shared_ptr<detail::LoggerBackend> backend;
  {
    std::lock_guard<std::mutex> lock(backend_mutex());
    backend = current_backend();
  }
  if (backend != nullptr) {
    backend->flush();
  }
}

Logger Logger::get(std::string module) {
  std::lock_guard<std::mutex> lock(backend_mutex());
  return Logger(current_backend(), std::move(module));
}

bool Logger::should_log(LogLevel level) const noexcept {
  return backend_ != nullptr && backend_->should_log(module_, level);
}

void Logger::log(LogLevel level, std::string event, std::string message, LogFields fields,
                 SourceLocation source) const {
  if (!should_log(level)) {
    return;
  }
  LogEvent record;
  record.level = level;
  record.module = module_;
  record.event = std::move(event);
  record.message = std::move(message);
  record.thread_id = std::hash<std::thread::id>{}(std::this_thread::get_id());
  record.source = source;
  record.fields = std::move(fields);
  log(std::move(record));
}

void Logger::log(LogEvent event) const {
  if (backend_ == nullptr) {
    return;
  }
  if (event.module.empty()) {
    event.module = module_;
  }
  if (event.thread_id == 0U) {
    event.thread_id = std::hash<std::thread::id>{}(std::this_thread::get_id());
  }
  if (!backend_->should_log(event.module, event.level)) {
    return;
  }
  backend_->emit(event);
}

void Logger::log_error(LogLevel level, std::string event, const Error& error, LogFields fields,
                       SourceLocation source) const {
  LogEvent record;
  record.level = level;
  record.module = module_;
  record.event = std::move(event);
  record.message = error.message();
  record.thread_id = std::hash<std::thread::id>{}(std::this_thread::get_id());
  record.source = source;
  record.fields = std::move(fields);
  record.error = error;
  log(std::move(record));
}

std::uint64_t Logger::dropped_log_count() const noexcept {
  return backend_ == nullptr ? 0U : backend_->dropped_log_count();
}

bool Logger::fallback_active() const noexcept {
  return backend_ != nullptr && backend_->fallback_active();
}

}  // namespace ros2_sdk
