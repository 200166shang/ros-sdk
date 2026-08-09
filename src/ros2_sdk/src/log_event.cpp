#include <ros2_sdk/log_event.hpp>

namespace ros2_sdk {

std::string LogEvent::render_text() const {
  std::string result;
  result.reserve(module.size() + event.size() + message.size() + 16U);
  result += log_level_name(level);
  if (!module.empty()) {
    result += " [";
    result += module;
    result += "]";
  }
  if (!event.empty()) {
    result += ' ';
    result += event;
  }
  if (!message.empty()) {
    result += ": ";
    result += message;
  }
  return result;
}

}  // namespace ros2_sdk
