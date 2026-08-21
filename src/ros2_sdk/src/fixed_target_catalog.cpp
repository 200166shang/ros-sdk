#include "fixed_target_catalog.hpp"

namespace ros2_sdk::skeleton {

std::optional<geometry_msgs::msg::PoseStamped> FixedTargetCatalog::resolve(
    const std::string& target_name) const {
  if (target_name != "pickup_a") {
    return std::nullopt;
  }

  geometry_msgs::msg::PoseStamped target;
  target.header.frame_id = "map";
  target.pose.position.x = 1.7;
  target.pose.position.y = -1.5;
  target.pose.orientation.w = 1.0;
  return target;
}

}  // namespace ros2_sdk::skeleton
