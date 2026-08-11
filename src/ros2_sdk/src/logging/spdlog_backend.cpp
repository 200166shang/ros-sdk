#include "spdlog_backend.hpp"

#include <spdlog/details/log_msg.h>
#include <spdlog/sinks/base_sink.h>
#include <spdlog/sinks/rotating_file_sink.h>
#include <spdlog/sinks/stdout_color_sinks.h>
#include <spdlog/spdlog.h>

#include <algorithm>
#include <chrono>
#include <filesystem>
#include <iostream>
#include <string>
#include <utility>
#include <vector>

namespace ros2_sdk::log::detail {
namespace {

spdlog::level::level_enum to_spdlog_level(Level level) noexcept {
  switch (level) {
    case Level::kTrace:
      return spdlog::level::trace;
    case Level::kDebug:
      return spdlog::level::debug;
    case Level::kInfo:
      return spdlog::level::info;
    case Level::kWarn:
      return spdlog::level::warn;
    case Level::kError:
      return spdlog::level::err;
    case Level::kCritical:
      return spdlog::level::critical;
    case Level::kOff:
      return spdlog::level::off;
  }
  return spdlog::level::off;
}

Level from_spdlog_level(spdlog::level::level_enum level) noexcept {
  switch (level) {
    case spdlog::level::trace:
      return Level::kTrace;
    case spdlog::level::debug:
      return Level::kDebug;
    case spdlog::level::info:
      return Level::kInfo;
    case spdlog::level::warn:
      return Level::kWarn;
    case spdlog::level::err:
      return Level::kError;
    case spdlog::level::critical:
      return Level::kCritical;
    case spdlog::level::off:
      return Level::kOff;
    default:
      return Level::kInfo;
  }
}

class CallbackSink final : public spdlog::sinks::base_sink<std::mutex> {
public:
  CallbackSink(LogCallback callback, std::atomic<std::uint64_t>* error_count)
      : callback_(std::move(callback)), error_count_(error_count) {}

protected:
  void sink_it_(const spdlog::details::log_msg& message) override {
    LogMessage record;
    record.time = message.time;
    record.level = from_spdlog_level(message.level);
    record.module.assign(message.logger_name.data(), message.logger_name.size());
    record.message.assign(message.payload.data(), message.payload.size());
    record.thread_id = message.thread_id;
    record.line = message.source.line >= 0 ? static_cast<std::uint32_t>(message.source.line) : 0U;
    record.file = message.source.filename == nullptr ? "" : message.source.filename;
    record.function = message.source.funcname == nullptr ? "" : message.source.funcname;

    try {
      callback_(record);
    } catch (...) {
      error_count_->fetch_add(1U, std::memory_order_relaxed);
    }
  }

  void flush_() override {}

private:
  LogCallback callback_;
  std::atomic<std::uint64_t>* error_count_;
};

class SafeSink final : public spdlog::sinks::base_sink<std::mutex> {
public:
  SafeSink(std::shared_ptr<spdlog::sinks::sink> sink, std::atomic<std::uint64_t>* error_count)
      : sink_(std::move(sink)), error_count_(error_count) {}

protected:
  void sink_it_(const spdlog::details::log_msg& message) override {
    try {
      sink_->log(message);
    } catch (...) {
      error_count_->fetch_add(1U, std::memory_order_relaxed);
      std::cerr.write(message.payload.data(), static_cast<std::streamsize>(message.payload.size()));
      std::cerr.put('\n');
    }
  }

  void flush_() override {
    try {
      sink_->flush();
    } catch (...) {
      error_count_->fetch_add(1U, std::memory_order_relaxed);
      std::cerr << "ros2_sdk logging sink flush failed\n";
    }
  }

private:
  std::shared_ptr<spdlog::sinks::sink> sink_;
  std::atomic<std::uint64_t>* error_count_;
};

class FanoutSink final : public spdlog::sinks::base_sink<std::mutex> {
public:
  FanoutSink(std::vector<std::shared_ptr<spdlog::sinks::sink>> sinks,
             std::shared_ptr<FlushCoordinator> flush_coordinator)
      : sinks_(std::move(sinks)), flush_coordinator_(std::move(flush_coordinator)) {}

protected:
  void sink_it_(const spdlog::details::log_msg& message) override {
    for (const auto& sink : sinks_) {
      try {
        sink->log(message);
      } catch (...) {
        std::cerr.write(message.payload.data(),
                        static_cast<std::streamsize>(message.payload.size()));
        std::cerr.put('\n');
      }
    }
  }

  void flush_() override {
    for (const auto& sink : sinks_) {
      try {
        sink->flush();
      } catch (...) {
        std::cerr << "ros2_sdk logging sink flush failed\n";
      }
    }
    flush_coordinator_->complete();
  }

private:
  std::vector<std::shared_ptr<spdlog::sinks::sink>> sinks_;
  std::shared_ptr<FlushCoordinator> flush_coordinator_;
};

}  // namespace

std::uint64_t FlushCoordinator::target(std::size_t flushes) {
  std::lock_guard<std::mutex> lock(mutex_);
  return completed_ + static_cast<std::uint64_t>(flushes);
}

void FlushCoordinator::complete() {
  {
    std::lock_guard<std::mutex> lock(mutex_);
    ++completed_;
  }
  condition_.notify_all();
}

bool FlushCoordinator::wait_for(std::uint64_t target_value) {
  std::unique_lock<std::mutex> lock(mutex_);
  return condition_.wait_for(lock, std::chrono::seconds(5),
                             [this, target_value] { return completed_ >= target_value; });
}

SpdlogBackend::SpdlogBackend(LogConfig config) : config_(std::move(config)) {}

SpdlogBackend::~SpdlogBackend() {
  accepting_.store(false, std::memory_order_release);
  thread_pool_.reset();
  fanout_sink_.reset();
  flush_coordinator_.reset();
}

Result<void> SpdlogBackend::start() {
  if (config_.queue_size == 0U || config_.worker_threads == 0U) {
    return Result<void>::failure(
        Error(ErrorCode::kInvalidArgument, "logging queue size and worker count must be positive"));
  }
  if (config_.file.has_value()) {
    const auto& file = config_.file.value();
    if (file.path.empty() || file.max_size_bytes == 0U || file.max_files == 0U) {
      return Result<void>::failure(
          Error(ErrorCode::kInvalidArgument, "logging file configuration is invalid"));
    }
  }

  try {
    flush_coordinator_ = std::make_shared<FlushCoordinator>();
    std::vector<std::shared_ptr<spdlog::sinks::sink>> sinks;
    constexpr const char* kPattern = "[%Y-%m-%d %H:%M:%S.%e] [%l] [%n] [thread %t] %v (%s:%# %!)";

    if (config_.console_enabled) {
      auto console = std::make_shared<spdlog::sinks::stdout_color_sink_mt>();
      console->set_pattern(kPattern);
      sinks.push_back(std::make_shared<SafeSink>(std::move(console), &sink_error_count_));
    }

    if (config_.file.has_value()) {
      const std::filesystem::path path(config_.file->path);
      if (!path.parent_path().empty()) {
        std::filesystem::create_directories(path.parent_path());
      }
      auto file = std::make_shared<spdlog::sinks::rotating_file_sink_mt>(
          path.string(), config_.file->max_size_bytes, config_.file->max_files);
      file->set_pattern(kPattern);
      sinks.push_back(std::make_shared<SafeSink>(std::move(file), &sink_error_count_));
    }

    if (config_.callback) {
      sinks.push_back(std::make_shared<SafeSink>(
          std::make_shared<CallbackSink>(config_.callback, &callback_error_count_),
          &sink_error_count_));
    }

    fanout_sink_ = std::make_shared<FanoutSink>(std::move(sinks), flush_coordinator_);
    thread_pool_ =
        std::make_shared<spdlog::details::thread_pool>(config_.queue_size, config_.worker_threads);
    accepting_.store(true, std::memory_order_release);
    return Result<void>::success();
  } catch (const std::exception& exception) {
    accepting_.store(false, std::memory_order_release);
    thread_pool_.reset();
    fanout_sink_.reset();
    flush_coordinator_.reset();
    return Result<void>::failure(Error(ErrorCode::kLoggingInitializationFailed, exception.what()));
  }
}

std::shared_ptr<ModuleLogger> SpdlogBackend::create_module_logger(const std::string& module) {
  if (!accepting_.load(std::memory_order_acquire) || thread_pool_ == nullptr ||
      fanout_sink_ == nullptr) {
    return nullptr;
  }

  auto result = std::make_shared<ModuleLogger>();
  result->logger = std::make_shared<spdlog::async_logger>(
      module, fanout_sink_, thread_pool_, spdlog::async_overflow_policy::overrun_oldest);
  result->logger->set_level(spdlog::level::trace);
  return result;
}

void SpdlogBackend::submit(const std::shared_ptr<ModuleLogger>& module_logger, Level level,
                           SourceLocation source, std::string_view message) noexcept {
  if (!accepting_.load(std::memory_order_acquire) || module_logger == nullptr ||
      module_logger->logger == nullptr) {
    return;
  }

  const spdlog::source_loc location{source.file == nullptr ? "" : source.file,
                                    static_cast<int>(source.line),
                                    source.function == nullptr ? "" : source.function};
  try {
    module_logger->logger->log(location, to_spdlog_level(level), "{}", message);
  } catch (...) {
    sink_error_count_.fetch_add(1U, std::memory_order_relaxed);
    std::cerr.write(message.data(), static_cast<std::streamsize>(message.size()));
    std::cerr.put('\n');
  }
}

void SpdlogBackend::flush(const std::vector<std::shared_ptr<ModuleLogger>>& modules) noexcept {
  if (modules.empty() || flush_coordinator_ == nullptr) {
    return;
  }

  const auto target_value = flush_coordinator_->target(1U);
  try {
    modules.front()->logger->flush();
    if (!flush_coordinator_->wait_for(target_value)) {
      sink_error_count_.fetch_add(1U, std::memory_order_relaxed);
    }
  } catch (...) {
    sink_error_count_.fetch_add(1U, std::memory_order_relaxed);
  }
}

void SpdlogBackend::shutdown(const std::vector<std::shared_ptr<ModuleLogger>>& modules) noexcept {
  accepting_.store(false, std::memory_order_release);
  flush(modules);
  thread_pool_.reset();
  fanout_sink_.reset();
  flush_coordinator_.reset();
}

LogStats SpdlogBackend::stats() const noexcept {
  LogStats result;
  if (thread_pool_ != nullptr) {
    result.dropped_count = thread_pool_->overrun_counter();
  }
  result.sink_error_count = sink_error_count_.load(std::memory_order_acquire);
  result.callback_error_count = callback_error_count_.load(std::memory_order_acquire);
  return result;
}

}  // namespace ros2_sdk::log::detail
