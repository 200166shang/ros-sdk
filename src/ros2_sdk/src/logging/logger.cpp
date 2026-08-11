#include <mutex>
#include <ros2_sdk/logging/logger.hpp>
#include <thread>
#include <utility>

#include "log_manager.hpp"

namespace ros2_sdk::log {
namespace {

std::mutex& global_mutex() {
  static std::mutex mutex;
  return mutex;
}

std::shared_ptr<detail::LogManager>& global_manager() {
  static std::shared_ptr<detail::LogManager> manager;
  return manager;
}

}  // namespace

Logger::Logger(std::shared_ptr<detail::LogManager> manager,
               std::shared_ptr<detail::ModuleLogger> module_logger, std::string module)
    : manager_(std::move(manager)),
      module_logger_(std::move(module_logger)),
      module_(std::move(module)) {}

bool Logger::should_log(Level level) const noexcept {
  return manager_ != nullptr && manager_->should_log(module_, level);
}

void Logger::log(Level level, SourceLocation source, std::string_view message) const noexcept {
  if (!should_log(level) || module_logger_ == nullptr) {
    return;
  }
  manager_->submit(module_logger_, module_, level, source, message);
}

Result<void> initialize(const LogConfig& config) {
  auto manager = std::make_shared<detail::LogManager>(config);
  auto result = manager->start();
  if (!result) {
    return result;
  }

  std::lock_guard<std::mutex> lock(global_mutex());
  if (global_manager() != nullptr) {
    manager->shutdown();
    return Result<void>::failure(
        Error(ErrorCode::kInvalidArgument, "logging has already been initialized"));
  }
  global_manager() = std::move(manager);
  return Result<void>::success();
}

void flush() noexcept {
  std::shared_ptr<detail::LogManager> manager;
  {
    std::lock_guard<std::mutex> lock(global_mutex());
    manager = global_manager();
  }
  if (manager != nullptr) {
    manager->flush();
  }
}

void shutdown() noexcept {
  std::shared_ptr<detail::LogManager> manager;
  {
    std::lock_guard<std::mutex> lock(global_mutex());
    manager = std::move(global_manager());
  }
  if (manager != nullptr) {
    manager->shutdown();
  }
}

Logger get_logger(std::string module) {
  std::lock_guard<std::mutex> lock(global_mutex());
  if (global_manager() == nullptr) {
    return Logger(nullptr, nullptr, std::move(module));
  }
  auto manager = global_manager();
  auto module_logger = manager->get_module_logger(module);
  return Logger(std::move(manager), std::move(module_logger), std::move(module));
}

Result<void> set_global_level(Level level) {
  std::shared_ptr<detail::LogManager> manager;
  {
    std::lock_guard<std::mutex> lock(global_mutex());
    manager = global_manager();
  }
  return manager == nullptr ? Result<void>::failure(
                                  Error(ErrorCode::kNotInitialized, "logging is not initialized"))
                            : manager->set_global_level(level);
}

Result<void> set_module_level(std::string module_prefix, Level level) {
  std::shared_ptr<detail::LogManager> manager;
  {
    std::lock_guard<std::mutex> lock(global_mutex());
    manager = global_manager();
  }
  return manager == nullptr ? Result<void>::failure(
                                  Error(ErrorCode::kNotInitialized, "logging is not initialized"))
                            : manager->set_module_level(std::move(module_prefix), level);
}

Result<void> clear_module_level(std::string_view module_prefix) {
  std::shared_ptr<detail::LogManager> manager;
  {
    std::lock_guard<std::mutex> lock(global_mutex());
    manager = global_manager();
  }
  return manager == nullptr ? Result<void>::failure(
                                  Error(ErrorCode::kNotInitialized, "logging is not initialized"))
                            : manager->clear_module_level(module_prefix);
}

LogStats stats() noexcept {
  std::shared_ptr<detail::LogManager> manager;
  {
    std::lock_guard<std::mutex> lock(global_mutex());
    manager = global_manager();
  }
  return manager == nullptr ? LogStats{} : manager->stats();
}

}  // namespace ros2_sdk::log
