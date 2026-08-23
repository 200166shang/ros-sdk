#ifndef ROS2_SDK__DELIVERY_SERVICE_HPP_
#define ROS2_SDK__DELIVERY_SERVICE_HPP_

#include <grpcpp/support/status.h>

#include <chrono>
#include <cstdint>
#include <functional>
#include <geometry_msgs/msg/pose_stamped.hpp>
#include <memory>
#include <mutex>
#include <optional>
#include <rclcpp/rclcpp.hpp>
#include <string>

#include "delivery.grpc.pb.h"

namespace ros2_sdk {

/** The one business seam between delivery state and robot navigation. */
class NavigationPort {
public:
  enum class Outcome { kSucceeded, kFailed, kCanceled };
  using FeedbackCallback = std::function<void(double)>;
  using ResultCallback = std::function<void(Outcome)>;

  virtual ~NavigationPort() = default;

  virtual bool ready(std::chrono::milliseconds timeout) const = 0;
  virtual void navigate(const geometry_msgs::msg::PoseStamped& target,
                        FeedbackCallback feedback_callback, ResultCallback result_callback) = 0;
  virtual void cancel() = 0;
};

class DeliveryService final :
    public delivery::DeliveryService::Service,
    public std::enable_shared_from_this<DeliveryService> {
public:
  explicit DeliveryService(rclcpp::Node::SharedPtr node);
  explicit DeliveryService(std::shared_ptr<NavigationPort> navigation);

  /** Return whether the real Nav2 action server is currently available. */
  bool ready(std::chrono::milliseconds timeout) const;

  grpc::Status CreateDelivery(grpc::ServerContext* context,
                              const delivery::CreateDeliveryRequest* request,
                              delivery::DeliverySnapshot* response) override;

  grpc::Status GetDelivery(grpc::ServerContext* context,
                           const delivery::GetDeliveryRequest* request,
                           delivery::DeliverySnapshot* response) override;

  grpc::Status ConfirmPickup(grpc::ServerContext* context,
                             const delivery::ConfirmDeliveryRequest* request,
                             delivery::DeliverySnapshot* response) override;

  grpc::Status ConfirmDropoff(grpc::ServerContext* context,
                              const delivery::ConfirmDeliveryRequest* request,
                              delivery::DeliverySnapshot* response) override;

  grpc::Status CancelDelivery(grpc::ServerContext* context,
                              const delivery::CancelDeliveryRequest* request,
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
  static bool is_terminal(delivery::DeliveryState state);
  static bool is_navigating(delivery::DeliveryState state);
  static grpc::Status invalid_state(const char* reason);

  void start_navigation(const std::string& task_id, const geometry_msgs::msg::PoseStamped& target,
                        delivery::DeliveryState navigating_state);
  void handle_feedback(const std::string& task_id, double distance_remaining);
  void handle_result(const std::string& task_id, delivery::DeliveryState navigating_state,
                     NavigationPort::Outcome outcome);

  rclcpp::Node::SharedPtr node_;
  std::shared_ptr<NavigationPort> navigation_;
  mutable std::mutex mutex_;
  std::optional<DeliveryTask> active_task_;
  std::uint64_t next_task_number_{1};
};

}  // namespace ros2_sdk

#endif  // ROS2_SDK__DELIVERY_SERVICE_HPP_
