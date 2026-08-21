#ifndef ROS2_SDK__NAVIGATION_ADAPTER_HPP_
#define ROS2_SDK__NAVIGATION_ADAPTER_HPP_

#include <chrono>
#include <cstdint>
#include <functional>
#include <optional>
#include <string>
#include <utility>

#include "navigation_task.hpp"

namespace ros2_sdk::skeleton {

enum class NavigationAdapterEventKind : std::uint8_t {
  kGoalAccepted,
  kGoalRejected,
  kFeedback,
  kResult,
  kCancelRejected,
};

enum class NavigationResultCode : std::uint8_t {
  kSucceeded,
  kCanceled,
  kAborted,
  kUnknown,
};

struct NavigationAdapterEvent {
  std::string task_id;
  NavigationAdapterEventKind kind{NavigationAdapterEventKind::kResult};
  NavigationResultCode result_code{NavigationResultCode::kUnknown};
  std::string message;
  std::string feedback;
  std::optional<NavigationOutcome> outcome;
};

using NavigationAdapterEventCallback = std::function<void(const NavigationAdapterEvent&)>;

class NavigationAdapter {
public:
  explicit NavigationAdapter(NavigationAdapterEventCallback event_callback = {})
      : event_callback_(std::move(event_callback)) {}
  virtual ~NavigationAdapter() = default;

  virtual void start(const NavigationTask& task) = 0;
  virtual void cancel(const std::string& task_id) = 0;
  virtual bool action_server_ready(std::chrono::milliseconds timeout) = 0;

protected:
  void emit_event(const NavigationAdapterEvent& event) const {
    if (event_callback_) {
      event_callback_(event);
    }
  }

private:
  NavigationAdapterEventCallback event_callback_;
};

}  // namespace ros2_sdk::skeleton

#endif  // ROS2_SDK__NAVIGATION_ADAPTER_HPP_
