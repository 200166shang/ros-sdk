#include <chrono>
#include <cstddef>
#include <iostream>
#include <ros2_sdk/logging/config.hpp>
#include <ros2_sdk/logging/level.hpp>
#include <ros2_sdk/logging/logger.hpp>
#include <string>
#include <thread>
#include <vector>

namespace {

using Clock = std::chrono::steady_clock;

void print_rate(const char* name, std::size_t count, std::chrono::duration<double> elapsed) {
  std::cout << name << ": " << count << " events in " << elapsed.count() << " seconds ("
            << static_cast<double>(count) / elapsed.count() << " events/s)\n";
}

bool initialize_quiet(ros2_sdk::log::LogConfig config) {
  config.console_enabled = false;
  return static_cast<bool>(ros2_sdk::log::initialize(config));
}

}  // namespace

int main() {
  constexpr std::size_t kCount = 100000U;

  ros2_sdk::log::LogConfig disabled;
  disabled.global_level = ros2_sdk::log::Level::kWarn;
  if (!initialize_quiet(disabled)) {
    return 1;
  }
  const auto disabled_logger = ros2_sdk::log::get_logger("benchmark.disabled");
  auto start = Clock::now();
  for (std::size_t index = 0; index < kCount; ++index) {
    SDK_LOG_DEBUG(disabled_logger, "disabled {}", index);
  }
  print_rate("disabled DEBUG", kCount, Clock::now() - start);
  ros2_sdk::log::shutdown();

  ros2_sdk::log::LogConfig enabled;
  enabled.callback = [](const ros2_sdk::log::LogMessage&) {
  };
  if (!initialize_quiet(enabled)) {
    return 1;
  }
  const auto enabled_logger = ros2_sdk::log::get_logger("benchmark.enabled");
  start = Clock::now();
  for (std::size_t index = 0; index < kCount; ++index) {
    SDK_LOG_INFO(enabled_logger, "enabled {}", index);
  }
  const auto producer_elapsed = Clock::now() - start;
  ros2_sdk::log::flush();
  print_rate("enabled producer", kCount, producer_elapsed);
  ros2_sdk::log::shutdown();

  ros2_sdk::log::LogConfig concurrent;
  concurrent.queue_size = 32768U;
  concurrent.callback = [](const ros2_sdk::log::LogMessage&) {
  };
  if (!initialize_quiet(concurrent)) {
    return 1;
  }
  const auto concurrent_logger = ros2_sdk::log::get_logger("benchmark.concurrent");
  constexpr int kThreadCount = 4;
  constexpr std::size_t kPerThread = kCount / kThreadCount;
  std::vector<std::thread> threads;
  start = Clock::now();
  for (int thread_index = 0; thread_index < kThreadCount; ++thread_index) {
    threads.emplace_back([concurrent_logger, thread_index] {
      for (std::size_t index = 0; index < kPerThread; ++index) {
        SDK_LOG_INFO(concurrent_logger, "thread={} event={}", thread_index, index);
      }
    });
  }
  for (auto& thread : threads) {
    thread.join();
  }
  const auto concurrent_elapsed = Clock::now() - start;
  ros2_sdk::log::flush();
  print_rate("concurrent producers", kCount, concurrent_elapsed);
  ros2_sdk::log::shutdown();

  ros2_sdk::log::LogConfig overflow;
  overflow.queue_size = 1U;
  overflow.callback = [](const ros2_sdk::log::LogMessage&) {
    std::this_thread::sleep_for(std::chrono::microseconds(100));
  };
  if (!initialize_quiet(overflow)) {
    return 1;
  }
  const auto overflow_logger = ros2_sdk::log::get_logger("benchmark.overflow");
  for (int index = 0; index < 1000; ++index) {
    SDK_LOG_INFO(overflow_logger, "overflow {}", index);
  }
  const auto overflow_stats = ros2_sdk::log::stats();
  std::cout << "overflow dropped: " << overflow_stats.dropped_count << "\n";
  ros2_sdk::log::shutdown();
  return 0;
}
