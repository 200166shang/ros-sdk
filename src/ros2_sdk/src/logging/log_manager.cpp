#include "log_manager.hpp"

#include <algorithm>
#include <utility>

namespace ros2_sdk::log::detail {
namespace {

bool module_prefix_matches(std::string_view module, std::string_view prefix) noexcept {
  if (module.size() < prefix.size() || module.compare(0U, prefix.size(), prefix) != 0) {
    return false;
  }
  return module.size() == prefix.size() || module[prefix.size()] == '.';
}

bool valid_module_prefix(std::string_view prefix) noexcept {
  return !prefix.empty() && prefix.front() != '.' && prefix.back() != '.' &&
         prefix.find("..") == std::string_view::npos;
}

}  // namespace

LogManager::LogManager(LogConfig config) : config_(std::move(config)) {}

LogManager::~LogManager() {
  shutdown();
}

Result<void> LogManager::start() {
  auto backend = std::make_shared<SpdlogBackend>(config_);
  auto result = backend->start();
  if (!result) {
    return result;
  }

  std::unique_lock<std::shared_mutex> lock(lifecycle_mutex_);
  backend_ = std::move(backend);
  accepting_ = true;
  return Result<void>::success();
}

void LogManager::shutdown() noexcept {
  std::shared_ptr<SpdlogBackend> backend;
  std::vector<std::shared_ptr<ModuleLogger>> modules;
  {
    std::unique_lock<std::shared_mutex> lock(lifecycle_mutex_);
    if (!accepting_ && backend_ == nullptr) {
      return;
    }
    accepting_ = false;
    backend = backend_;
    {
      std::lock_guard<std::mutex> modules_lock(modules_mutex_);
      for (const auto& [module, logger] : modules_) {
        static_cast<void>(module);
        modules.push_back(logger);
      }
    }
  }

  if (backend != nullptr) {
    backend->shutdown(modules);
  }

  {
    std::unique_lock<std::shared_mutex> lock(lifecycle_mutex_);
    std::lock_guard<std::mutex> modules_lock(modules_mutex_);
    modules_.clear();
    backend_.reset();
  }
}

void LogManager::flush() noexcept {
  std::shared_ptr<SpdlogBackend> backend;
  std::vector<std::shared_ptr<ModuleLogger>> modules;
  {
    std::shared_lock<std::shared_mutex> lock(lifecycle_mutex_);
    if (!accepting_ || backend_ == nullptr) {
      return;
    }
    backend = backend_;
    std::lock_guard<std::mutex> modules_lock(modules_mutex_);
    for (const auto& [module, logger] : modules_) {
      static_cast<void>(module);
      modules.push_back(logger);
    }
  }
  backend->flush(modules);
}

bool LogManager::should_log(std::string_view module, Level level) const noexcept {
  std::shared_lock<std::shared_mutex> lock(lifecycle_mutex_);
  return should_log_unlocked(module, level);
}

bool LogManager::should_log_unlocked(std::string_view module, Level level) const noexcept {
  if (!accepting_ || backend_ == nullptr || level == Level::kOff) {
    return false;
  }
  Level minimum = config_.global_level;
  std::size_t best_length = 0U;
  for (const auto& [prefix, prefix_level] : module_levels_) {
    if (prefix.size() > best_length && module_prefix_matches(module, prefix)) {
      minimum = prefix_level;
      best_length = prefix.size();
    }
  }
  return level_enabled(level, minimum);
}

std::shared_ptr<ModuleLogger> LogManager::get_module_logger(const std::string& module) {
  std::shared_lock<std::shared_mutex> lifecycle_lock(lifecycle_mutex_);
  if (!accepting_ || backend_ == nullptr) {
    return nullptr;
  }
  std::lock_guard<std::mutex> modules_lock(modules_mutex_);
  const auto existing = modules_.find(module);
  if (existing != modules_.end()) {
    return existing->second;
  }
  auto logger = backend_->create_module_logger(module);
  modules_.emplace(module, logger);
  return logger;
}

void LogManager::submit(const std::shared_ptr<ModuleLogger>& module_logger, std::string_view module,
                        Level level, SourceLocation source, std::string_view message) noexcept {
  std::shared_lock<std::shared_mutex> lock(lifecycle_mutex_);
  if (!accepting_ || backend_ == nullptr || !module_logger || !should_log_unlocked(module, level)) {
    return;
  }
  backend_->submit(module_logger, level, source, message);
}

Result<void> LogManager::set_global_level(Level level) {
  std::unique_lock<std::shared_mutex> lock(lifecycle_mutex_);
  if (!accepting_) {
    return Result<void>::failure(Error(ErrorCode::kNotInitialized, "logging is not initialized"));
  }
  config_.global_level = level;
  return Result<void>::success();
}

Result<void> LogManager::set_module_level(std::string module_prefix, Level level) {
  if (!valid_module_prefix(module_prefix)) {
    return Result<void>::failure(
        Error(ErrorCode::kInvalidArgument, "module prefix must be a non-empty dot-separated name"));
  }
  std::unique_lock<std::shared_mutex> lock(lifecycle_mutex_);
  if (!accepting_) {
    return Result<void>::failure(Error(ErrorCode::kNotInitialized, "logging is not initialized"));
  }
  module_levels_[std::move(module_prefix)] = level;
  return Result<void>::success();
}

Result<void> LogManager::clear_module_level(std::string_view module_prefix) {
  if (!valid_module_prefix(module_prefix)) {
    return Result<void>::failure(
        Error(ErrorCode::kInvalidArgument, "module prefix must be a non-empty dot-separated name"));
  }
  std::unique_lock<std::shared_mutex> lock(lifecycle_mutex_);
  if (!accepting_) {
    return Result<void>::failure(Error(ErrorCode::kNotInitialized, "logging is not initialized"));
  }
  module_levels_.erase(std::string(module_prefix));
  return Result<void>::success();
}

LogStats LogManager::stats() const noexcept {
  std::shared_lock<std::shared_mutex> lock(lifecycle_mutex_);
  return backend_ == nullptr ? LogStats{} : backend_->stats();
}

}  // namespace ros2_sdk::log::detail
