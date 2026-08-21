#ifndef ROS2_SDK__NAV2_NAVIGATION_ADAPTER_HPP_
#define ROS2_SDK__NAV2_NAVIGATION_ADAPTER_HPP_

#include <chrono>
#include <memory>
#include <mutex>
#include <nav2_msgs/action/navigate_to_pose.hpp>
#include <rclcpp/rclcpp.hpp>
#include <rclcpp_action/rclcpp_action.hpp>
#include <string>
#include <unordered_map>

#include "fixed_target_catalog.hpp"
#include "navigation_adapter.hpp"

namespace ros2_sdk::skeleton {

class Nav2NavigationAdapter final :
    public NavigationAdapter,
    public std::enable_shared_from_this<Nav2NavigationAdapter> {
public:
  using Action = nav2_msgs::action::NavigateToPose;
  using GoalHandle = rclcpp_action::ClientGoalHandle<Action>;

  explicit Nav2NavigationAdapter(
      rclcpp::Node::SharedPtr node, NavigationAdapterEventCallback event_callback,
      std::chrono::milliseconds action_server_timeout = std::chrono::seconds(5),
      const std::string& action_name = "navigate_to_pose");

  void start(const NavigationTask& task) override;
  void cancel(const std::string& task_id) override;
  bool action_server_ready(std::chrono::milliseconds timeout) override;

private:
  struct ActiveGoal {
    bool cancel_requested{false};
    bool cancel_sent{false};
    GoalHandle::SharedPtr goal_handle;
  };

  void handle_goal_response(const std::string& task_id, const GoalHandle::SharedPtr& goal_handle);
  void handle_feedback(const std::string& task_id, const Action::Feedback& feedback);
  void handle_result(const std::string& task_id, const GoalHandle::WrappedResult& result);
  void cancel_goal_if_needed(const std::string& task_id, const GoalHandle::SharedPtr& goal_handle);
  static NavigationResultCode result_code(const GoalHandle::WrappedResult& result);

  rclcpp::Node::SharedPtr node_;
  rclcpp_action::Client<Action>::SharedPtr client_;
  std::chrono::milliseconds action_server_timeout_;
  FixedTargetCatalog target_catalog_;
  mutable std::mutex mutex_;
  std::unordered_map<std::string, ActiveGoal> active_goals_;
};

}  // namespace ros2_sdk::skeleton

#endif  // ROS2_SDK__NAV2_NAVIGATION_ADAPTER_HPP_
