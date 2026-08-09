#ifndef ROS2_SDK__LOG_FIELD_HPP_
#define ROS2_SDK__LOG_FIELD_HPP_

#include <cstdint>
#include <string>
#include <utility>
#include <variant>
#include <vector>

namespace ros2_sdk {

using LogFieldValue =
    std::variant<std::nullptr_t, bool, std::int64_t, std::uint64_t, double, std::string>;

// LogField is a flat, strongly typed value attached to a log event.
struct LogField {
  LogField(std::string field_name, std::nullptr_t field_value)
      : key(std::move(field_name)), value(field_value) {}

  LogField(std::string field_name, bool field_value)
      : key(std::move(field_name)), value(field_value) {}

  LogField(std::string field_name, std::int64_t field_value)
      : key(std::move(field_name)), value(field_value) {}

  LogField(std::string field_name, std::uint64_t field_value)
      : key(std::move(field_name)), value(field_value) {}

  LogField(std::string field_name, double field_value)
      : key(std::move(field_name)), value(field_value) {}

  LogField(std::string field_name, std::string field_value)
      : key(std::move(field_name)), value(std::move(field_value)) {}

  LogField(std::string field_name, const char* field_value)
      : key(std::move(field_name)), value(std::string(field_value == nullptr ? "" : field_value)) {}

  std::string key;
  LogFieldValue value;
};

using LogFields = std::vector<LogField>;

}  // namespace ros2_sdk

#endif  // ROS2_SDK__LOG_FIELD_HPP_
