#ifndef ROS2_SDK__NAVIGATION_ACTION_CLIENT_HPP_
#define ROS2_SDK__NAVIGATION_ACTION_CLIENT_HPP_

#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <functional>
#include <geometry_msgs/msg/pose_stamped.hpp>
#include <memory>
#include <mutex>
#include <nav2_msgs/action/navigate_to_pose.hpp>
#include <optional>
#include <rclcpp/rclcpp.hpp>
#include <rclcpp_action/rclcpp_action.hpp>
#include <string>

namespace ros2_sdk::skeleton {

enum class NavigationOutcomeCode : std::uint8_t {
  kSucceeded,
  kInvalidTarget,
  kActionServerUnavailable,
  kGoalRejected,
  kAborted,
  kTimeout,
  kInternalError,
};

struct NavigationOutcome {
  NavigationOutcomeCode code;
  std::string message;
};

class NavigationActionClient final : public std::enable_shared_from_this<NavigationActionClient> {
public:
  using Action = nav2_msgs::action::NavigateToPose;
  using GoalHandle = rclcpp_action::ClientGoalHandle<Action>;
  using CancellationPredicate = std::function<bool()>;

  explicit NavigationActionClient(
      rclcpp::Node::SharedPtr node,
      std::chrono::milliseconds action_server_timeout = std::chrono::seconds(5),
      const std::string& action_name = "navigate_to_pose");

  NavigationOutcome navigate(const std::string& target_name, std::chrono::milliseconds timeout,
                             const CancellationPredicate& is_cancelled = {});

  bool action_server_ready(std::chrono::milliseconds timeout);

private:
  struct PendingRequest {
    std::condition_variable condition;
    std::mutex mutex;
    bool terminal{false};
    std::optional<NavigationOutcome> outcome;
    GoalHandle::SharedPtr goal_handle;
  };

  static std::optional<geometry_msgs::msg::PoseStamped> resolve_target(
      const rclcpp::Node& node, const std::string& target_name);
  static void complete(const std::shared_ptr<PendingRequest>& pending, NavigationOutcome outcome);
  static NavigationOutcome map_result(
      const rclcpp_action::ClientGoalHandle<Action>::WrappedResult& result);

  rclcpp::Node::SharedPtr node_;
  rclcpp_action::Client<Action>::SharedPtr client_;
  std::chrono::milliseconds action_server_timeout_;
};

}  // namespace ros2_sdk::skeleton

#endif  // ROS2_SDK__NAVIGATION_ACTION_CLIENT_HPP_
