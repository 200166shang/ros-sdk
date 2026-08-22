#ifndef ROS2_SDK__DELIVERY_SERVICE_HPP_
#define ROS2_SDK__DELIVERY_SERVICE_HPP_

#include <grpcpp/support/status.h>

#include <chrono>
#include <cstdint>
#include <memory>
#include <mutex>
#include <nav2_msgs/action/navigate_to_pose.hpp>
#include <optional>
#include <rclcpp/rclcpp.hpp>
#include <rclcpp_action/rclcpp_action.hpp>
#include <string>

#include "delivery.grpc.pb.h"

namespace ros2_sdk {

class DeliveryService final :
    public delivery::DeliveryService::Service,
    public std::enable_shared_from_this<DeliveryService> {
public:
  using Action = nav2_msgs::action::NavigateToPose;
  using GoalHandle = rclcpp_action::ClientGoalHandle<Action>;

  explicit DeliveryService(rclcpp::Node::SharedPtr node);

  /** Return whether the real Nav2 action server is currently available. */
  bool ready(std::chrono::milliseconds timeout) const;

  grpc::Status CreateDelivery(grpc::ServerContext* context,
                              const delivery::CreateDeliveryRequest* request,
                              delivery::DeliverySnapshot* response) override;

  grpc::Status GetDelivery(grpc::ServerContext* context,
                           const delivery::GetDeliveryRequest* request,
                           delivery::DeliverySnapshot* response) override;

private:
  struct DeliveryTask {
    std::string task_id;
    std::string request_id;
    std::string pickup_location;
    std::string dropoff_location;
    delivery::DeliveryState state{delivery::DELIVERY_STATE_UNSPECIFIED};
    std::string current_target;
    std::optional<double> remaining_distance_m;
  };

  static std::optional<geometry_msgs::msg::PoseStamped> resolve_location(
      const std::string& location_name);
  static void fill_snapshot(const DeliveryTask& task, delivery::DeliverySnapshot* response);

  void start_pickup_navigation(const std::string& task_id,
                               const geometry_msgs::msg::PoseStamped& target);
  void handle_goal_response(const std::string& task_id, const GoalHandle::SharedPtr& goal_handle);
  void handle_feedback(const std::string& task_id, const Action::Feedback& feedback);
  void handle_result(const std::string& task_id, const GoalHandle::WrappedResult& result);

  rclcpp::Node::SharedPtr node_;
  rclcpp_action::Client<Action>::SharedPtr action_client_;
  mutable std::mutex mutex_;
  std::optional<DeliveryTask> active_task_;
  std::uint64_t next_task_number_{1};
};

}  // namespace ros2_sdk

#endif  // ROS2_SDK__DELIVERY_SERVICE_HPP_
