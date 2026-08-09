#include "spdlog_backend.hpp"

#include <spdlog/async_logger.h>
#include <spdlog/details/thread_pool.h>
#include <spdlog/sinks/base_sink.h>
#include <spdlog/sinks/rotating_file_sink.h>
#include <spdlog/spdlog.h>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <ctime>
#include <filesystem>
#include <iomanip>
#include <iostream>
#include <mutex>
#include <nlohmann/json.hpp>
#include <sstream>
#include <string>
#include <type_traits>
#include <utility>

namespace ros2_sdk::detail {
namespace {

using Json = nlohmann::json;

spdlog::level::level_enum to_spdlog_level(LogLevel level) noexcept {
  switch (level) {
    case LogLevel::kDebug:
      return spdlog::level::debug;
    case LogLevel::kInfo:
      return spdlog::level::info;
    case LogLevel::kWarn:
      return spdlog::level::warn;
    case LogLevel::kError:
      return spdlog::level::err;
    case LogLevel::kFatal:
      return spdlog::level::critical;
    case LogLevel::kOff:
      return spdlog::level::off;
  }
  return spdlog::level::off;
}

LogLevel from_spdlog_level(spdlog::level::level_enum level) noexcept {
  switch (level) {
    case spdlog::level::debug:
    case spdlog::level::trace:
      return LogLevel::kDebug;
    case spdlog::level::info:
      return LogLevel::kInfo;
    case spdlog::level::warn:
      return LogLevel::kWarn;
    case spdlog::level::err:
      return LogLevel::kError;
    case spdlog::level::critical:
      return LogLevel::kFatal;
    case spdlog::level::off:
      return LogLevel::kOff;
    default:
      return LogLevel::kInfo;
  }
}

std::string format_timestamp(std::chrono::system_clock::time_point timestamp) {
  const auto milliseconds =
      std::chrono::duration_cast<std::chrono::milliseconds>(timestamp.time_since_epoch()) % 1000;
  const std::time_t time = std::chrono::system_clock::to_time_t(timestamp);
  std::tm utc_time{};
#if defined(_WIN32)
  gmtime_s(&utc_time, &time);
#else
  gmtime_r(&time, &utc_time);
#endif
  std::ostringstream output;
  output << std::put_time(&utc_time, "%Y-%m-%dT%H:%M:%S") << '.' << std::setfill('0')
         << std::setw(3) << milliseconds.count() << 'Z';
  return output.str();
}

void set_field(Json& output, const LogField& field) {
  const auto assign = [&output, &field](const auto& value) {
    output[field.key] = value;
  };
  std::visit(
      [&assign](const auto& value) {
        using Value = std::decay_t<decltype(value)>;
        if constexpr (std::is_same_v<Value, std::nullptr_t>) {
          assign(nullptr);
        } else {
          assign(value);
        }
      },
      field.value);
}

Json event_to_json(const LogEvent& event) {
  Json output;
  output["timestamp"] = format_timestamp(event.timestamp);
  output["level"] = log_level_name(event.level);
  output["module"] = event.module;
  output["event"] = event.event;
  output["message"] = event.message;
  output["thread_id"] = event.thread_id;
  if (event.source.file != nullptr && event.source.file[0] != '\0') {
    output["source_file"] = event.source.file;
    output["source_line"] = event.source.line;
    output["source_function"] = event.source.function == nullptr ? "" : event.source.function;
  }
  Json custom_fields = Json::object();
  for (const auto& field : event.fields) {
    if (output.contains(field.key) || field.key == "fields") {
      set_field(custom_fields, field);
    } else {
      set_field(output, field);
    }
  }
  if (!custom_fields.empty()) {
    output["fields"] = std::move(custom_fields);
  }
  if (event.error.has_value()) {
    output["error_code"] = error_code_value(event.error->code());
    output["error_name"] = error_code_name(event.error->code());
    output["error_message"] = event.error->message();
  }
  return output;
}

class FanoutSink final : public spdlog::sinks::base_sink<std::mutex> {
public:
  using FileSink = spdlog::sinks::rotating_file_sink_mt;

  FanoutSink(std::shared_ptr<FileSink> file_sink, const LoggerConfig& config,
             std::atomic<bool>* fallback_active, std::function<void(bool)> on_complete)
      : file_sink_(std::move(file_sink)),
        config_(config),
        fallback_active_(fallback_active),
        on_complete_(std::move(on_complete)) {}

  bool accepts(LogLevel level) const noexcept {
    return (config_.console.enabled && log_level_enabled(level, config_.console.level)) ||
           (config_.file.enabled && log_level_enabled(level, config_.file.level)) ||
           (config_.rosout.enabled && config_.rosout_callback != nullptr &&
            log_level_enabled(level, config_.rosout.level));
  }

protected:
  void sink_it_(const spdlog::details::log_msg& message) override {
    const LogLevel level = from_spdlog_level(message.level);
    const std::string payload(message.payload.data(), message.payload.size());
    std::string text = payload;
    try {
      const Json event = Json::parse(payload);
      text = event.value("text", payload);
    } catch (const std::exception&) {
      // The file payload is already the best available fallback if serialization is malformed.
    }

    try {
      if (config_.file.enabled && log_level_enabled(level, config_.file.level)) {
        if (file_sink_ != nullptr) {
          try {
            file_sink_->log(message);
          } catch (const std::exception&) {
            file_sink_.reset();
            fallback_active_->store(true, std::memory_order_release);
          }
        }
        if (file_sink_ == nullptr) {
          std::cerr << payload << '\n';
        }
      }
      if (config_.console.enabled && log_level_enabled(level, config_.console.level)) {
        std::clog << text << '\n';
      }
      if (config_.rosout.enabled && config_.rosout_callback != nullptr &&
          log_level_enabled(level, config_.rosout.level)) {
        try {
          config_.rosout_callback(level, text);
        } catch (const std::exception&) {
          // A logging sink must not recursively report its own failure.
        }
      }
    } catch (const std::exception&) {
      fallback_active_->store(true, std::memory_order_release);
      std::cerr << payload << '\n';
    }

    if (on_complete_ != nullptr) {
      on_complete_(level != LogLevel::kError && level != LogLevel::kFatal);
    }
  }

  void flush_() override {
    if (file_sink_ != nullptr) {
      file_sink_->flush();
    }
    std::clog.flush();
    std::cerr.flush();
  }

private:
  std::shared_ptr<FileSink> file_sink_;
  LoggerConfig config_;
  std::atomic<bool>* fallback_active_;
  std::function<void(bool)> on_complete_;
};

}  // namespace

class LoggerBackend::Impl {
public:
  explicit Impl(LoggerConfig config) : config_(std::move(config)) {}

  Result<void> start() {
    if (config_.file.max_size == 0U || config_.file.max_files == 0U ||
        config_.critical_queue_size == 0U) {
      return Result<void>::failure(
          Error(ErrorCode::kInvalidArgument, "logging size and retention values must be positive"));
    }

    std::shared_ptr<spdlog::sinks::rotating_file_sink_mt> file_sink;
    if (config_.file.enabled) {
      try {
        std::filesystem::create_directories(config_.file.directory);
        const auto path = config_.file.directory / config_.file.name;
        file_sink = std::make_shared<spdlog::sinks::rotating_file_sink_mt>(
            path.string(), config_.file.max_size, config_.file.max_files);
        file_sink->set_pattern("%v");
      } catch (const std::exception&) {
        fallback_active_.store(true, std::memory_order_release);
      }
    }

    const auto on_complete = [this](bool normal) {
      auto& pending_counter = normal ? normal_pending_ : critical_pending_;
      std::size_t pending = pending_counter.load(std::memory_order_relaxed);
      while (pending > 0U &&
             !pending_counter.compare_exchange_weak(
                 pending, pending - 1U, std::memory_order_release, std::memory_order_relaxed)) {
      }
      pending_cv_.notify_all();
    };
    fanout_sink_ =
        std::make_shared<FanoutSink>(std::move(file_sink), config_, &fallback_active_, on_complete);

    normal_pool_ = std::make_shared<spdlog::details::thread_pool>(
        std::max<std::size_t>(config_.normal_queue_size, 1U), 1U);
    critical_pool_ =
        std::make_shared<spdlog::details::thread_pool>(config_.critical_queue_size, 1U);
    normal_logger_ =
        std::make_shared<spdlog::async_logger>("ros2_sdk.normal", fanout_sink_, normal_pool_,
                                               spdlog::async_overflow_policy::overrun_oldest);
    critical_logger_ = std::make_shared<spdlog::async_logger>(
        "ros2_sdk.critical", fanout_sink_, critical_pool_, spdlog::async_overflow_policy::block);
    normal_logger_->set_level(spdlog::level::trace);
    critical_logger_->set_level(spdlog::level::trace);
    accepting_.store(true, std::memory_order_release);
    return Result<void>::success();
  }

  void shutdown() noexcept {
    if (!accepting_.exchange(false, std::memory_order_acq_rel)) {
      return;
    }
    try {
      flush();
      normal_logger_.reset();
      critical_logger_.reset();
      normal_pool_.reset();
      critical_pool_.reset();
      fanout_sink_.reset();
    } catch (const std::exception&) {
      fallback_active_.store(true, std::memory_order_release);
    }
  }

  void flush() noexcept {
    try {
      if (normal_logger_ != nullptr) {
        normal_logger_->flush();
      }
      if (critical_logger_ != nullptr) {
        critical_logger_->flush();
      }
      std::unique_lock<std::mutex> lock(pending_mutex_);
      pending_cv_.wait_for(lock, std::chrono::seconds(5), [this] {
        return normal_pending_.load(std::memory_order_acquire) == 0U &&
               critical_pending_.load(std::memory_order_acquire) == 0U;
      });
    } catch (const std::exception&) {
      fallback_active_.store(true, std::memory_order_release);
    }
  }

  bool should_log(std::string_view module, LogLevel level) const noexcept {
    if (!accepting_.load(std::memory_order_acquire) ||
        !log_level_enabled(level, config_.effective_level(module))) {
      return false;
    }
    return fanout_sink_ != nullptr;
  }

  void emit(const LogEvent& event) noexcept {
    if (!should_log(event.module, event.level) || fanout_sink_ == nullptr ||
        !fanout_sink_->accepts(event.level)) {
      return;
    }
    const bool normal = event.level != LogLevel::kError && event.level != LogLevel::kFatal;
    if (normal) {
      const std::size_t limit = config_.normal_queue_size;
      std::size_t pending = normal_pending_.load(std::memory_order_relaxed);
      while (pending < limit &&
             !normal_pending_.compare_exchange_weak(
                 pending, pending + 1U, std::memory_order_acquire, std::memory_order_relaxed)) {
      }
      if (pending >= limit) {
        dropped_log_count_.fetch_add(1U, std::memory_order_relaxed);
        return;
      }
    }

    if (!normal) {
      critical_pending_.fetch_add(1U, std::memory_order_acquire);
    }
    const auto release_pending = [this, normal] {
      if (normal) {
        normal_pending_.fetch_sub(1U, std::memory_order_release);
      } else {
        critical_pending_.fetch_sub(1U, std::memory_order_release);
      }
      pending_cv_.notify_all();
    };
    std::string payload;
    try {
      Json record = event_to_json(event);
      record["text"] = event.render_text();
      payload = record.dump();
    } catch (const std::exception&) {
      release_pending();
      fallback_active_.store(true, std::memory_order_release);
      return;
    }
    try {
      auto& logger = normal ? normal_logger_ : critical_logger_;
      logger->log(to_spdlog_level(event.level), payload);
      if ((!normal && config_.flush_on_error && event.level == LogLevel::kError) ||
          (!normal && config_.flush_on_fatal && event.level == LogLevel::kFatal)) {
        logger->flush();
      }
    } catch (const std::exception&) {
      release_pending();
      fallback_active_.store(true, std::memory_order_release);
    }
  }

  std::uint64_t dropped_log_count() const noexcept {
    return dropped_log_count_.load(std::memory_order_acquire);
  }

  bool fallback_active() const noexcept { return fallback_active_.load(std::memory_order_acquire); }

private:
  LoggerConfig config_;
  std::shared_ptr<FanoutSink> fanout_sink_;
  std::shared_ptr<spdlog::details::thread_pool> normal_pool_;
  std::shared_ptr<spdlog::details::thread_pool> critical_pool_;
  std::shared_ptr<spdlog::async_logger> normal_logger_;
  std::shared_ptr<spdlog::async_logger> critical_logger_;
  std::atomic<bool> accepting_{false};
  std::atomic<bool> fallback_active_{false};
  std::atomic<std::size_t> normal_pending_{0U};
  std::atomic<std::size_t> critical_pending_{0U};
  std::atomic<std::uint64_t> dropped_log_count_{0U};
  std::mutex pending_mutex_;
  std::condition_variable pending_cv_;
};

LoggerBackend::LoggerBackend(LoggerConfig config)
    : impl_(std::make_unique<Impl>(std::move(config))) {}

LoggerBackend::~LoggerBackend() {
  shutdown();
}

Result<void> LoggerBackend::start() {
  return impl_->start();
}

void LoggerBackend::shutdown() noexcept {
  impl_->shutdown();
}

void LoggerBackend::flush() noexcept {
  impl_->flush();
}

bool LoggerBackend::should_log(std::string_view module, LogLevel level) const noexcept {
  return impl_->should_log(module, level);
}

void LoggerBackend::emit(const LogEvent& event) noexcept {
  impl_->emit(event);
}

std::uint64_t LoggerBackend::dropped_log_count() const noexcept {
  return impl_->dropped_log_count();
}

bool LoggerBackend::fallback_active() const noexcept {
  return impl_->fallback_active();
}

Result<std::shared_ptr<LoggerBackend>> make_logger_backend(const LoggerConfig& config) {
  auto backend = std::make_shared<LoggerBackend>(config);
  const auto result = backend->start();
  if (!result) {
    return Result<std::shared_ptr<LoggerBackend>>::failure(result.error());
  }
  return Result<std::shared_ptr<LoggerBackend>>::success(std::move(backend));
}

}  // namespace ros2_sdk::detail
