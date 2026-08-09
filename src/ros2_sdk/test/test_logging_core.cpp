#include <gtest/gtest.h>

#include <chrono>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <memory>
#include <nlohmann/json.hpp>
#include <ros2_sdk/log_event.hpp>
#include <ros2_sdk/log_field.hpp>
#include <ros2_sdk/log_level.hpp>
#include <ros2_sdk/logger.hpp>
#include <ros2_sdk/logger_config.hpp>
#include <string>
#include <thread>
#include <vector>

namespace ros2_sdk {
namespace {

class LoggingCoreTest : public ::testing::Test {
protected:
  void TearDown() override { Logger::shutdown(); }
};

TEST(LogLevelTest, OrdersLevelsForFiltering) {
  EXPECT_LT(log_level_value(LogLevel::kDebug), log_level_value(LogLevel::kInfo));
  EXPECT_LT(log_level_value(LogLevel::kInfo), log_level_value(LogLevel::kWarn));
  EXPECT_LT(log_level_value(LogLevel::kWarn), log_level_value(LogLevel::kError));
  EXPECT_LT(log_level_value(LogLevel::kError), log_level_value(LogLevel::kFatal));
  EXPECT_EQ(log_level_name(LogLevel::kFatal), "FATAL");
}

TEST(LogFieldTest, StoresSupportedFlatTypes) {
  const LogFields fields = {LogField("null_value", nullptr),
                            LogField("enabled", true),
                            LogField("signed", std::int64_t{-7}),
                            LogField("unsigned", std::uint64_t{9}),
                            LogField("ratio", 1.25),
                            LogField("name", "controller")};

  ASSERT_EQ(fields.size(), 6U);
  EXPECT_EQ(std::get<bool>(fields[1].value), true);
  EXPECT_EQ(std::get<std::int64_t>(fields[2].value), -7);
  EXPECT_EQ(std::get<std::string>(fields[5].value), "controller");
}

TEST(LogEventTest, RendersStableHumanReadableText) {
  LogEvent event;
  event.timestamp = std::chrono::system_clock::from_time_t(0);
  event.level = LogLevel::kError;
  event.module = "rosbridge.lifecycle";
  event.event = "module_start_failed";
  event.message = "controller did not become ready";
  event.thread_id = 42;
  event.source = SourceLocation{"lifecycle.cpp", 17, "start"};

  EXPECT_EQ(event.render_text(),
            "ERROR [rosbridge.lifecycle] module_start_failed: controller did not become ready");
}

TEST_F(LoggingCoreTest, FiltersByHierarchicalModuleLevel) {
  LoggerConfig config = LoggerConfig::defaults();
  config.console.enabled = false;
  config.file.enabled = false;
  config.module_levels["rosbridge.lifecycle"] = LogLevel::kWarn;
  ASSERT_TRUE(Logger::initialize(config));

  const Logger logger = Logger::get("rosbridge.lifecycle.node");
  EXPECT_FALSE(logger.should_log(LogLevel::kInfo));
  EXPECT_TRUE(logger.should_log(LogLevel::kWarn));
}

TEST_F(LoggingCoreTest, WritesStructuredEventsToJsonLines) {
  const auto directory = std::filesystem::temp_directory_path() / "ros2_sdk_logging_core_test";
  std::filesystem::remove_all(directory);

  LoggerConfig config = LoggerConfig::defaults();
  config.console.enabled = false;
  config.rosout.enabled = false;
  config.file.enabled = true;
  config.file.directory = directory;
  config.file.name = "events.jsonl";
  ASSERT_TRUE(Logger::initialize(config));

  Logger::get("rosbridge.test")
      .log(LogLevel::kInfo, "startup", "ready",
           {LogField("attempt", std::int64_t{1}), LogField("enabled", true)});
  Logger::flush();

  std::ifstream input(directory / "events.jsonl");
  ASSERT_TRUE(input.is_open());
  const std::string line((std::istreambuf_iterator<char>(input)), std::istreambuf_iterator<char>());
  EXPECT_NE(line.find("\"module\":\"rosbridge.test\""), std::string::npos);
  EXPECT_NE(line.find("\"event\":\"startup\""), std::string::npos);
  EXPECT_NE(line.find("\"attempt\":1"), std::string::npos);
  EXPECT_NE(line.find("\"enabled\":true"), std::string::npos);
}

TEST_F(LoggingCoreTest, DropsNormalLogsAtBoundedQueueAndCountsThem) {
  LoggerConfig config = LoggerConfig::defaults();
  config.console.enabled = false;
  config.file.directory = std::filesystem::temp_directory_path() / "ros2_sdk_logging_drop_test";
  config.file.name = "dropped.jsonl";
  config.normal_queue_size = 0;
  config.critical_queue_size = 1;
  ASSERT_TRUE(Logger::initialize(config));

  const Logger logger = Logger::get("rosbridge.high_rate");
  for (int i = 0; i < 1000; ++i) {
    logger.log(LogLevel::kInfo, "sample", "payload");
  }

  EXPECT_GT(logger.dropped_log_count(), 0U);
}

TEST_F(LoggingCoreTest, RecordsErrorsWithoutChoosingRecoveryAction) {
  const auto directory = std::filesystem::temp_directory_path() / "ros2_sdk_logging_error_test";
  std::filesystem::remove_all(directory);

  LoggerConfig config = LoggerConfig::defaults();
  config.console.enabled = false;
  config.file.directory = directory;
  config.file.name = "errors.jsonl";
  ASSERT_TRUE(Logger::initialize(config));

  const Error error(ErrorCode::kCommunicationTimeout, "service timed out");
  Logger::get("rosbridge.client").log_error(LogLevel::kError, "request_failed", error);
  Logger::flush();

  std::ifstream input(directory / "errors.jsonl");
  const std::string line((std::istreambuf_iterator<char>(input)), std::istreambuf_iterator<char>());
  EXPECT_NE(line.find("\"error_code\":2001"), std::string::npos);
  EXPECT_NE(line.find("\"error_name\":\"COMMUNICATION_TIMEOUT\""), std::string::npos);
  EXPECT_NE(line.find("\"error_message\":\"service timed out\""), std::string::npos);
}

TEST_F(LoggingCoreTest, FlushesFatalWithoutAbortingTheProcess) {
  const auto directory = std::filesystem::temp_directory_path() / "ros2_sdk_logging_fatal_test";
  std::filesystem::remove_all(directory);

  LoggerConfig config = LoggerConfig::defaults();
  config.console.enabled = false;
  config.file.directory = directory;
  config.file.name = "fatal.jsonl";
  ASSERT_TRUE(Logger::initialize(config));

  Logger::get("rosbridge.fatal").log(LogLevel::kFatal, "safety_stop", "fatal is a severity");
  Logger::flush();

  std::ifstream input(directory / "fatal.jsonl");
  const std::string line((std::istreambuf_iterator<char>(input)), std::istreambuf_iterator<char>());
  EXPECT_NE(line.find("\"level\":\"FATAL\""), std::string::npos);
  EXPECT_NE(line.find("\"event\":\"safety_stop\""), std::string::npos);
}

TEST_F(LoggingCoreTest, AcceptsConcurrentEventsFromMultipleThreads) {
  const auto directory = std::filesystem::temp_directory_path() / "ros2_sdk_logging_thread_test";
  std::filesystem::remove_all(directory);

  LoggerConfig config = LoggerConfig::defaults();
  config.console.enabled = false;
  config.file.directory = directory;
  config.file.name = "threaded.jsonl";
  config.normal_queue_size = 2048U;
  ASSERT_TRUE(Logger::initialize(config));

  constexpr int kThreadCount = 4;
  constexpr int kEventsPerThread = 100;
  std::vector<std::thread> threads;
  threads.reserve(kThreadCount);
  for (int thread_index = 0; thread_index < kThreadCount; ++thread_index) {
    threads.emplace_back([thread_index] {
      const Logger logger = Logger::get("rosbridge.concurrent");
      for (int event_index = 0; event_index < kEventsPerThread; ++event_index) {
        logger.log(LogLevel::kInfo, "sample", "concurrent",
                   {LogField("thread", std::int64_t{thread_index}),
                    LogField("index", std::int64_t{event_index})});
      }
    });
  }
  for (auto& thread : threads) {
    thread.join();
  }
  Logger::flush();

  std::ifstream input(directory / "threaded.jsonl");
  std::size_t line_count = 0U;
  std::string line;
  while (std::getline(input, line)) {
    ++line_count;
  }
  EXPECT_EQ(line_count, static_cast<std::size_t>(kThreadCount * kEventsPerThread));
}

TEST(LoggerConfigTest, LoadsJsonAndCommandLineOverrides) {
  const auto path = std::filesystem::temp_directory_path() / "ros2_sdk_logging_config.json";
  {
    std::ofstream output(path);
    output << R"({
      "level": "WARN",
      "console": {"enabled": false},
      "file": {"directory": "runtime-logs", "max_files": 2},
      "modules": {"rosbridge.lifecycle": "DEBUG"}
    })";
  }

  auto result = LoggerConfig::from_file(path);
  ASSERT_TRUE(result);
  LoggerConfig config = result.value();
  EXPECT_EQ(config.global_level, LogLevel::kWarn);
  EXPECT_FALSE(config.console.enabled);
  EXPECT_EQ(config.file.directory, "runtime-logs");
  EXPECT_EQ(config.file.max_files, 2U);
  EXPECT_EQ(config.effective_level("rosbridge.lifecycle.node"), LogLevel::kDebug);

  const char* argv[] = {"test", "--log-level=ERROR", "--log-console", "--log-critical-queue=8"};
  ASSERT_TRUE(config.apply_command_line(4, argv));
  EXPECT_EQ(config.global_level, LogLevel::kError);
  EXPECT_TRUE(config.console.enabled);
  EXPECT_EQ(config.critical_queue_size, 8U);
}

TEST_F(LoggingCoreTest, RotatesFilesAndRetainsConfiguredCount) {
  const auto directory = std::filesystem::temp_directory_path() / "ros2_sdk_logging_rotation_test";
  std::filesystem::remove_all(directory);

  LoggerConfig config = LoggerConfig::defaults();
  config.console.enabled = false;
  config.file.directory = directory;
  config.file.name = "events.jsonl";
  config.file.max_size = 256U;
  config.file.max_files = 2U;
  ASSERT_TRUE(Logger::initialize(config));

  const std::string message(160U, 'x');
  const Logger logger = Logger::get("rosbridge.rotation");
  for (int index = 0; index < 20; ++index) {
    logger.log(LogLevel::kInfo, "large_event", message);
  }
  Logger::flush();

  std::size_t file_count = 0U;
  for (const auto& entry : std::filesystem::directory_iterator(directory)) {
    if (entry.path().filename().string().find("events") == 0U) {
      ++file_count;
    }
  }
  EXPECT_GT(file_count, 1U);
  EXPECT_LE(file_count, 3U);
}

TEST_F(LoggingCoreTest, FallsBackWhenLogDirectoryCannotBeCreated) {
  const auto parent = std::filesystem::temp_directory_path() / "ros2_sdk_logging_fallback_test";
  std::filesystem::remove_all(parent);
  std::filesystem::create_directories(parent);
  const auto invalid_directory = parent / "not-a-directory";
  std::ofstream(invalid_directory) << "occupied";

  LoggerConfig config = LoggerConfig::defaults();
  config.console.enabled = false;
  config.file.directory = invalid_directory;
  ASSERT_TRUE(Logger::initialize(config));
  EXPECT_TRUE(Logger::get("rosbridge.fallback").fallback_active());

  Logger::get("rosbridge.fallback").log(LogLevel::kError, "write_failed", "fallback path");
  Logger::flush();
}

TEST_F(LoggingCoreTest, RejectsRepeatedInitialization) {
  LoggerConfig config = LoggerConfig::defaults();
  config.console.enabled = false;
  config.file.enabled = false;
  ASSERT_TRUE(Logger::initialize(config));
  EXPECT_FALSE(Logger::initialize(config));
}

}  // namespace
}  // namespace ros2_sdk
