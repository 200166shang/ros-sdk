#include <gtest/gtest.h>
#include <spdlog/spdlog.h>

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <functional>
#include <memory>
#include <mutex>
#include <ros2_sdk/logging/config.hpp>
#include <ros2_sdk/logging/level.hpp>
#include <ros2_sdk/logging/log.hpp>
#include <ros2_sdk/logging/logger.hpp>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

namespace ros2_sdk::log {
namespace {

class LoggingTest : public ::testing::Test {
protected:
  void TearDown() override { shutdown(); }

  static std::filesystem::path test_path(const char* name) {
    const auto path = std::filesystem::temp_directory_path() / "ros2_sdk_logging_core" / name;
    std::filesystem::remove_all(path.parent_path());
    std::filesystem::create_directories(path.parent_path());
    return path;
  }
};

TEST(LevelTest, PreservesSeverityOrderingAndNames) {
  EXPECT_LT(level_value(Level::kTrace), level_value(Level::kDebug));
  EXPECT_LT(level_value(Level::kDebug), level_value(Level::kInfo));
  EXPECT_LT(level_value(Level::kInfo), level_value(Level::kWarn));
  EXPECT_LT(level_value(Level::kWarn), level_value(Level::kError));
  EXPECT_LT(level_value(Level::kError), level_value(Level::kCritical));
  EXPECT_EQ(level_name(Level::kCritical), "CRITICAL");
}

TEST(RedactTest, NeverStoresOrFormatsTheOriginalValue) {
  const std::string secret = "token-that-must-not-appear";
  const auto output = fmt::format("credential={}", redact(secret));

  EXPECT_EQ(output, "credential=[REDACTED]");
  EXPECT_EQ(output.find(secret), std::string::npos);
}

TEST_F(LoggingTest, FiltersBeforeFormattingArguments) {
  LogConfig config;
  config.global_level = Level::kWarn;
  config.console_enabled = false;
  ASSERT_TRUE(initialize(config));

  int evaluations = 0;
  const auto argument = [&evaluations] {
    ++evaluations;
    return std::string("should not be formatted");
  };

  SDK_LOG_INFO(get_logger("transport"), "{}", argument());

  EXPECT_EQ(evaluations, 0);
}

TEST_F(LoggingTest, EvaluatesLoggerExpressionOnce) {
  LogConfig config;
  config.console_enabled = false;
  ASSERT_TRUE(initialize(config));

  std::atomic<int> callback_count{0};
  config.callback = [&callback_count](const LogMessage&) {
    ++callback_count;
  };
  shutdown();
  ASSERT_TRUE(initialize(config));

  int logger_evaluations = 0;
  const auto get_test_logger = [&logger_evaluations] {
    ++logger_evaluations;
    return get_logger("macro.once");
  };

  SDK_LOG_INFO(get_test_logger(), "ready");
  flush();

  EXPECT_EQ(logger_evaluations, 1);
  EXPECT_EQ(callback_count.load(), 1);
}

TEST_F(LoggingTest, SendsOneHumanReadableMessageToCallbackAndFile) {
  const auto path = test_path("events.log");
  std::mutex mutex;
  std::condition_variable condition;
  std::vector<LogMessage> messages;

  LogConfig config;
  config.console_enabled = false;
  config.file = RotatingFileConfig{path.string(), 4096U, 2U};
  config.callback = [&mutex, &condition, &messages](const LogMessage& message) {
    {
      std::lock_guard<std::mutex> lock(mutex);
      messages.push_back(message);
    }
    condition.notify_all();
  };
  ASSERT_TRUE(initialize(config));

  const auto logger = get_logger("transport.grpc");
  logger.log(Level::kError, SourceLocation{"transport.cpp", 27U, "connect"}, "request failed: {}",
             redact("secret"));
  flush();

  {
    std::unique_lock<std::mutex> lock(mutex);
    ASSERT_TRUE(condition.wait_for(lock, std::chrono::seconds(2),
                                   [&messages] { return messages.size() == 1U; }));
  }

  ASSERT_EQ(messages.size(), 1U);
  EXPECT_EQ(messages[0].module, "transport.grpc");
  EXPECT_EQ(messages[0].message, "request failed: [REDACTED]");
  EXPECT_EQ(messages[0].file, "transport.cpp");
  EXPECT_EQ(messages[0].function, "connect");
  EXPECT_EQ(messages[0].line, 27U);
  EXPECT_NE(messages[0].thread_id, 0U);

  std::ifstream input(path);
  ASSERT_TRUE(input.is_open());
  const std::string file_contents((std::istreambuf_iterator<char>(input)), {});
  EXPECT_NE(file_contents.find("request failed: [REDACTED]"), std::string::npos);
  EXPECT_EQ(file_contents.find("secret"), std::string::npos);
}

TEST_F(LoggingTest, MacroCapturesCallsiteAndCallbackRunsOffProducerThread) {
  std::mutex mutex;
  std::condition_variable condition;
  LogMessage received;
  std::thread::id callback_thread;
  const auto producer_thread = std::this_thread::get_id();

  LogConfig config;
  config.console_enabled = false;
  config.callback = [&mutex, &condition, &received, &callback_thread](const LogMessage& message) {
    {
      std::lock_guard<std::mutex> lock(mutex);
      received = message;
      callback_thread = std::this_thread::get_id();
    }
    condition.notify_all();
  };
  ASSERT_TRUE(initialize(config));

  SDK_LOG_INFO(get_logger("macro.callsite"), "callsite captured");
  flush();

  std::unique_lock<std::mutex> lock(mutex);
  ASSERT_TRUE(condition.wait_for(lock, std::chrono::seconds(2),
                                 [&received] { return received.message == "callsite captured"; }));
  EXPECT_NE(received.file, "");
  EXPECT_NE(received.function, "");
  EXPECT_GT(received.line, 0U);
  EXPECT_NE(callback_thread, producer_thread);
}

TEST_F(LoggingTest, UsesLongestModulePrefixAndUpdatesExistingLoggers) {
  LogConfig config;
  config.global_level = Level::kInfo;
  config.console_enabled = false;
  ASSERT_TRUE(initialize(config));

  const auto logger = get_logger("transport.grpc.client");
  EXPECT_TRUE(logger.should_log(Level::kInfo));

  ASSERT_TRUE(set_module_level("transport", Level::kDebug));
  ASSERT_TRUE(set_module_level("transport.grpc", Level::kError));
  EXPECT_FALSE(logger.should_log(Level::kWarn));
  EXPECT_TRUE(logger.should_log(Level::kError));
  EXPECT_TRUE(get_logger("transport.http").should_log(Level::kDebug));

  ASSERT_TRUE(clear_module_level("transport.grpc"));
  EXPECT_TRUE(logger.should_log(Level::kWarn));
  EXPECT_FALSE(logger.should_log(Level::kTrace));
}

TEST_F(LoggingTest, OnceAndThrottleAreSafeAtOneCallSite) {
  std::atomic<int> callback_count{0};
  LogConfig config;
  config.console_enabled = false;
  config.callback = [&callback_count](const LogMessage&) {
    ++callback_count;
  };
  ASSERT_TRUE(initialize(config));

  const auto logger = get_logger("rate-limited");
  for (int index = 0; index < 10; ++index) {
    SDK_LOG_WARN_ONCE(logger, "only once");
    SDK_LOG_WARN_THROTTLE(logger, std::chrono::milliseconds(100), "throttled");
  }
  flush();

  EXPECT_EQ(callback_count.load(), 2);
}

TEST_F(LoggingTest, AcceptsConcurrentProducers) {
  std::atomic<int> callback_count{0};
  LogConfig config;
  config.queue_size = 8192U;
  config.console_enabled = false;
  config.callback = [&callback_count](const LogMessage&) {
    ++callback_count;
  };
  ASSERT_TRUE(initialize(config));

  std::vector<std::thread> producers;
  for (int thread_index = 0; thread_index < 4; ++thread_index) {
    producers.emplace_back([thread_index] {
      const auto logger = get_logger("concurrent");
      for (int index = 0; index < 100; ++index) {
        SDK_LOG_INFO(logger, "producer={} index={}", thread_index, index);
      }
    });
  }
  for (auto& producer : producers) {
    producer.join();
  }
  flush();

  EXPECT_EQ(callback_count.load(), 400);
}

TEST_F(LoggingTest, CountsOverrunsAndCallbackFailuresWithoutThrowing) {
  std::atomic<int> callback_count{0};
  LogConfig config;
  config.queue_size = 1U;
  config.console_enabled = false;
  config.callback = [&callback_count](const LogMessage&) {
    ++callback_count;
    throw std::runtime_error("callback failure");
  };
  ASSERT_TRUE(initialize(config));

  const auto logger = get_logger("slow-callback");
  for (int index = 0; index < 1000; ++index) {
    SDK_LOG_INFO(logger, "event {}", index);
  }
  flush();

  const auto result = stats();
  EXPECT_GT(result.dropped_count, 0U);
  EXPECT_GT(result.callback_error_count, 0U);
  EXPECT_GT(callback_count.load(), 0);
}

TEST_F(LoggingTest, RejectsInvalidConfigurationAndRepeatedInitialization) {
  LogConfig invalid;
  invalid.queue_size = 0U;
  const auto invalid_result = initialize(invalid);
  ASSERT_FALSE(invalid_result);
  EXPECT_EQ(invalid_result.error().code(), ErrorCode::kInvalidArgument);

  LogConfig config;
  config.console_enabled = false;
  ASSERT_TRUE(initialize(config));
  const auto repeated = initialize(config);
  ASSERT_FALSE(repeated);
  EXPECT_EQ(repeated.error().code(), ErrorCode::kInvalidArgument);

  shutdown();
  LogConfig invalid_file;
  invalid_file.console_enabled = false;
  const auto invalid_path = test_path("invalid-file");
  std::filesystem::create_directories(invalid_path);
  invalid_file.file = RotatingFileConfig{invalid_path.string(), 1024U, 1U};
  const auto file_result = initialize(invalid_file);
  ASSERT_FALSE(file_result);
  EXPECT_EQ(file_result.error().code(), ErrorCode::kLoggingInitializationFailed);
}

TEST_F(LoggingTest, CanReinitializeAfterShutdownAndDoesNotTouchSpdlogRegistry) {
  const auto before = spdlog::get("ros2_sdk.logging.registry_test");
  const auto default_logger_name = spdlog::default_logger()->name();

  LogConfig config;
  config.console_enabled = false;
  ASSERT_TRUE(initialize(config));
  EXPECT_EQ(spdlog::get("ros2_sdk.logging.registry_test"), before);
  EXPECT_EQ(spdlog::default_logger()->name(), default_logger_name);

  const auto old_logger = get_logger("old");
  shutdown();
  old_logger.log(Level::kInfo, SourceLocation{}, "old handle is safe");

  ASSERT_TRUE(initialize(config));
  EXPECT_EQ(spdlog::get("ros2_sdk.logging.registry_test"), before);
  EXPECT_EQ(spdlog::default_logger()->name(), default_logger_name);
}

TEST_F(LoggingTest, ShutdownDrainsAcceptedMessages) {
  std::atomic<int> callback_count{0};
  LogConfig config;
  config.console_enabled = false;
  config.callback = [&callback_count](const LogMessage&) {
    ++callback_count;
  };
  ASSERT_TRUE(initialize(config));

  const auto logger = get_logger("shutdown");
  for (int index = 0; index < 20; ++index) {
    SDK_LOG_INFO(logger, "message {}", index);
  }
  shutdown();

  EXPECT_EQ(callback_count.load(), 20);
}

}  // namespace
}  // namespace ros2_sdk::log
