#include "navigation_task.hpp"

namespace ros2_sdk::skeleton {

bool is_terminal(TaskState state) {
  return state == TaskState::kSucceeded || state == TaskState::kCanceled ||
         state == TaskState::kRejected || state == TaskState::kFailed;
}

}  // namespace ros2_sdk::skeleton
