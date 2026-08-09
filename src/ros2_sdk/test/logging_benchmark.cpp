#include <chrono>
#include <filesystem>
#include <iostream>
#include <ros2_sdk/logger.hpp>
#include <ros2_sdk/logger_config.hpp>
#include <string>

namespace {

using Clock = std::chrono::steady_clock;

void print_rate(const char* name, std::size_t count, std::chrono::duration<double> elapsed) {
  const double rate = static_cast<double>(count) / elapsed.count();
  std::cout << name << ": " << count << " events in " << elapsed.count() << " seconds (" << rate
            << " events/s)\n";
}

}  // namespace

int main() {
  constexpr std::size_t kCount = 100000U;
  ros2_sdk::LoggerConfig config = ros2_sdk::LoggerConfig::defaults();
  config.console.enabled = false;
  config.file.enabled = false;
  config.rosout.enabled = false;
  config.normal_queue_size = 8192U;
  config.critical_queue_size = 256U;
  if (!ros2_sdk::Logger::initialize(config)) {
    std::cerr << "failed to initialize disabled-output benchmark\n";
    return 1;
  }

  const auto disabled_logger = ros2_sdk::Logger::get("rosbridge.benchmark");
  auto start = Clock::now();
  for (std::size_t index = 0; index < kCount; ++index) {
    disabled_logger.log(ros2_sdk::LogLevel::kDebug, "disabled", "payload");
  }
  print_rate("disabled DEBUG", kCount, Clock::now() - start);
  ros2_sdk::Logger::shutdown();

  config.file.enabled = true;
  config.file.directory = std::filesystem::temp_directory_path() / "ros2_sdk_logging_benchmark";
  config.file.name = "events.jsonl";
  config.file.max_size = 256U * 1024U * 1024U;
  config.file.max_files = 1U;
  if (!ros2_sdk::Logger::initialize(config)) {
    std::cerr << "failed to initialize file-output benchmark\n";
    return 1;
  }

  const auto enabled_logger = ros2_sdk::Logger::get("rosbridge.benchmark");
  start = Clock::now();
  for (std::size_t index = 0; index < kCount; ++index) {
    enabled_logger.log(ros2_sdk::LogLevel::kInfo, "enabled", "payload");
  }
  ros2_sdk::Logger::flush();
  print_rate("enabled JSONL", kCount, Clock::now() - start);
  ros2_sdk::Logger::shutdown();
  return 0;
}
