#ifndef ROS2_SDK__NAVIGATION_TASK_HPP_
#define ROS2_SDK__NAVIGATION_TASK_HPP_

#include <cstdint>
#include <optional>
#include <string>

#include "navigation_outcome.hpp"

namespace ros2_sdk::skeleton {

enum class TaskState : std::uint8_t {
  kAccepted,
  kRunning,
  kCanceling,
  kSucceeded,
  kCanceled,
  kRejected,
  kFailed,
};

struct NavigationTask {
  std::string task_id;
  std::string target_name;
  TaskState state{TaskState::kAccepted};
  std::string message;
  std::string feedback;
  std::optional<NavigationOutcome> outcome;
};

enum class TaskEventKind : std::uint8_t { kState, kFeedback };

struct TaskEvent {
  NavigationTask task;
  TaskEventKind kind{TaskEventKind::kState};
};

bool is_terminal(TaskState state);

}  // namespace ros2_sdk::skeleton

#endif  // ROS2_SDK__NAVIGATION_TASK_HPP_
