#include <cstdlib>
#include <fstream>
#include <nlohmann/json.hpp>
#include <ros2_sdk/logger_config.hpp>
#include <sstream>
#include <string>

namespace ros2_sdk {
namespace {

using Json = nlohmann::json;

Result<LogLevel> parse_level_value(const Json& value, std::string_view key) {
  if (!value.is_string()) {
    return Result<LogLevel>::failure(
        Error(ErrorCode::kInvalidArgument, std::string(key) + " must be a string"));
  }
  const auto parsed = parse_log_level(value.get<std::string>());
  if (!parsed.has_value()) {
    return Result<LogLevel>::failure(
        Error(ErrorCode::kInvalidArgument, std::string(key) + " has an unknown level"));
  }
  return Result<LogLevel>::success(*parsed);
}

Result<bool> parse_bool_value(const Json& value, std::string_view key) {
  if (!value.is_boolean()) {
    return Result<bool>::failure(
        Error(ErrorCode::kInvalidArgument, std::string(key) + " must be a boolean"));
  }
  return Result<bool>::success(value.get<bool>());
}

Result<void> apply_level(std::string_view value, LogLevel& destination, std::string_view source) {
  const auto parsed = parse_log_level(value);
  if (!parsed.has_value()) {
    return Result<void>::failure(
        Error(ErrorCode::kInvalidArgument, std::string(source) + " has an unknown level"));
  }
  destination = *parsed;
  return Result<void>::success();
}

Result<void> apply_bool(std::string_view value, bool& destination, std::string_view source) {
  if (value == "1" || value == "true" || value == "TRUE" || value == "on") {
    destination = true;
    return Result<void>::success();
  }
  if (value == "0" || value == "false" || value == "FALSE" || value == "off") {
    destination = false;
    return Result<void>::success();
  }
  return Result<void>::failure(
      Error(ErrorCode::kInvalidArgument, std::string(source) + " must be boolean"));
}

Result<void> apply_size(std::string_view value, std::size_t& destination, std::string_view source) {
  try {
    const auto parsed = std::stoull(std::string(value));
    if (parsed == 0U) {
      return Result<void>::failure(
          Error(ErrorCode::kInvalidArgument, std::string(source) + " must be greater than zero"));
    }
    destination = static_cast<std::size_t>(parsed);
  } catch (const std::exception&) {
    return Result<void>::failure(
        Error(ErrorCode::kInvalidArgument, std::string(source) + " must be an integer"));
  }
  return Result<void>::success();
}

Result<void> apply_json_config(const Json& json, LoggerConfig& config) {
  if (!json.is_object()) {
    return Result<void>::failure(
        Error(ErrorCode::kInvalidArgument, "logging config must be object"));
  }

  if (json.contains("level")) {
    const auto result = parse_level_value(json.at("level"), "level");
    if (!result) {
      return Result<void>::failure(result.error());
    }
    config.global_level = result.value();
  }
  if (json.contains("normal_queue_size")) {
    config.normal_queue_size = json.at("normal_queue_size").get<std::size_t>();
  }
  if (json.contains("critical_queue_size")) {
    config.critical_queue_size = json.at("critical_queue_size").get<std::size_t>();
  }
  if (json.contains("flush_on_error")) {
    const auto result = parse_bool_value(json.at("flush_on_error"), "flush_on_error");
    if (!result) {
      return Result<void>::failure(result.error());
    }
    config.flush_on_error = result.value();
  }
  if (json.contains("flush_on_fatal")) {
    const auto result = parse_bool_value(json.at("flush_on_fatal"), "flush_on_fatal");
    if (!result) {
      return Result<void>::failure(result.error());
    }
    config.flush_on_fatal = result.value();
  }

  const auto apply_sink = [](const Json& source, bool& enabled, LogLevel& level,
                             std::string_view name) {
    if (source.contains("enabled")) {
      const auto result = parse_bool_value(source.at("enabled"), std::string(name) + ".enabled");
      if (!result) {
        return Result<void>::failure(result.error());
      }
      enabled = result.value();
    }
    if (source.contains("level")) {
      const auto result = parse_level_value(source.at("level"), std::string(name) + ".level");
      if (!result) {
        return Result<void>::failure(result.error());
      }
      level = result.value();
    }
    return Result<void>::success();
  };

  if (json.contains("console")) {
    const auto result =
        apply_sink(json.at("console"), config.console.enabled, config.console.level, "console");
    if (!result) {
      return result;
    }
  }
  if (json.contains("rosout")) {
    const auto result =
        apply_sink(json.at("rosout"), config.rosout.enabled, config.rosout.level, "rosout");
    if (!result) {
      return result;
    }
  }
  if (json.contains("file")) {
    const auto& source = json.at("file");
    const auto result = apply_sink(source, config.file.enabled, config.file.level, "file");
    if (!result) {
      return result;
    }
    if (source.contains("directory")) {
      config.file.directory = source.at("directory").get<std::string>();
    }
    if (source.contains("name")) {
      config.file.name = source.at("name").get<std::string>();
    }
    if (source.contains("max_size")) {
      config.file.max_size = source.at("max_size").get<std::size_t>();
    }
    if (source.contains("max_files")) {
      config.file.max_files = source.at("max_files").get<std::size_t>();
    }
  }
  if (json.contains("modules")) {
    if (!json.at("modules").is_object()) {
      return Result<void>::failure(Error(ErrorCode::kInvalidArgument, "modules must be an object"));
    }
    for (const auto& [module, level] : json.at("modules").items()) {
      const auto result = parse_level_value(level, "modules." + module);
      if (!result) {
        return Result<void>::failure(result.error());
      }
      config.module_levels[module] = result.value();
    }
  }
  return Result<void>::success();
}

Result<void> apply_option(std::string_view option, LoggerConfig& config) {
  const auto separator = option.find('=');
  const auto name = option.substr(0, separator);
  const auto value =
      separator == std::string_view::npos ? std::string_view{} : option.substr(separator + 1);

  if (name == "--log-level") {
    return apply_level(value, config.global_level, "--log-level");
  }
  if (name == "--log-dir") {
    if (value.empty()) {
      return Result<void>::failure(Error(ErrorCode::kInvalidArgument, "--log-dir needs a value"));
    }
    config.file.directory = value;
    return Result<void>::success();
  }
  if (name == "--log-file") {
    if (value.empty()) {
      return Result<void>::failure(Error(ErrorCode::kInvalidArgument, "--log-file needs a value"));
    }
    config.file.name = value;
    return Result<void>::success();
  }
  if (name == "--log-console" || name == "--no-log-console") {
    return apply_bool(name == "--log-console" ? "true" : "false", config.console.enabled, name);
  }
  if (name == "--log-rosout" || name == "--no-log-rosout") {
    return apply_bool(name == "--log-rosout" ? "true" : "false", config.rosout.enabled, name);
  }
  if (name == "--log-normal-queue") {
    return apply_size(value, config.normal_queue_size, name);
  }
  if (name == "--log-critical-queue") {
    return apply_size(value, config.critical_queue_size, name);
  }
  return Result<void>::success();
}

}  // namespace

LoggerConfig LoggerConfig::defaults() {
  return LoggerConfig{};
}

LogLevel LoggerConfig::effective_level(std::string_view module) const noexcept {
  LogLevel result = global_level;
  std::size_t best_length = 0U;
  for (const auto& [prefix, level] : module_levels) {
    if (module.size() < prefix.size() || module.compare(0U, prefix.size(), prefix) != 0) {
      continue;
    }
    if (module.size() != prefix.size() && module[prefix.size()] != '.') {
      continue;
    }
    if (prefix.size() > best_length) {
      result = level;
      best_length = prefix.size();
    }
  }
  return result;
}

Result<LoggerConfig> LoggerConfig::from_file(const std::filesystem::path& path) {
  std::ifstream input(path);
  if (!input.is_open()) {
    return Result<LoggerConfig>::failure(
        Error(ErrorCode::kInvalidArgument, "cannot open logging config: " + path.string()));
  }
  try {
    const Json json = Json::parse(input);
    LoggerConfig config = defaults();
    const auto result = apply_json_config(json, config);
    if (!result) {
      return Result<LoggerConfig>::failure(result.error());
    }
    return Result<LoggerConfig>::success(std::move(config));
  } catch (const std::exception& exception) {
    return Result<LoggerConfig>::failure(Error(
        ErrorCode::kInvalidArgument, "invalid logging config: " + std::string(exception.what())));
  }
}

Result<void> LoggerConfig::apply_environment() {
  const auto apply_env = [](const char* name, auto&& apply) -> Result<void> {
    const char* value = std::getenv(name);
    return value == nullptr ? Result<void>::success() : apply(std::string_view(value));
  };

  auto result = apply_env("ROS2_SDK_LOG_LEVEL", [&](std::string_view value) {
    return apply_level(value, global_level, "ROS2_SDK_LOG_LEVEL");
  });
  if (!result) {
    return result;
  }
  result = apply_env("ROS2_SDK_LOG_DIR", [&](std::string_view value) {
    file.directory = value;
    return Result<void>::success();
  });
  if (!result) {
    return result;
  }
  result = apply_env("ROS2_SDK_LOG_FILE", [&](std::string_view value) {
    file.name = value;
    return Result<void>::success();
  });
  if (!result) {
    return result;
  }
  result = apply_env("ROS2_SDK_LOG_CONSOLE", [&](std::string_view value) {
    return apply_bool(value, console.enabled, "ROS2_SDK_LOG_CONSOLE");
  });
  if (!result) {
    return result;
  }
  return apply_env("ROS2_SDK_LOG_ROSOUT", [&](std::string_view value) {
    return apply_bool(value, rosout.enabled, "ROS2_SDK_LOG_ROSOUT");
  });
}

Result<void> LoggerConfig::apply_command_line(int argc, const char* const argv[]) {
  for (int index = 1; index < argc; ++index) {
    const std::string_view option(argv[index] == nullptr ? "" : argv[index]);
    if (option.rfind("--log-", 0U) != 0U) {
      continue;
    }
    const auto result = apply_option(option, *this);
    if (!result) {
      return result;
    }
  }
  return Result<void>::success();
}

}  // namespace ros2_sdk
