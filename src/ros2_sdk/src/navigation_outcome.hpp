#ifndef ROS2_SDK__NAVIGATION_OUTCOME_HPP_
#define ROS2_SDK__NAVIGATION_OUTCOME_HPP_

#include <cstdint>
#include <string>

namespace ros2_sdk::skeleton {

// TaskState describes lifecycle ownership; NavigationOutcome describes the
// terminal reason returned by the navigation backend.
enum class NavigationOutcomeCode : std::uint8_t {
  kSucceeded,
  kInvalidTarget,
  kActionServerUnavailable,
  kGoalRejected,
  kAborted,
  kTimeout,
  kInternalError,
  kCanceled,
  kFailed,
};

struct NavigationOutcome {
  NavigationOutcomeCode code;
  std::string message;
};

}  // namespace ros2_sdk::skeleton

#endif  // ROS2_SDK__NAVIGATION_OUTCOME_HPP_
