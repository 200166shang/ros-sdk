#ifndef ROS2_SDK__FIXED_TARGET_CATALOG_HPP_
#define ROS2_SDK__FIXED_TARGET_CATALOG_HPP_

#include <geometry_msgs/msg/pose_stamped.hpp>
#include <optional>
#include <string>

namespace ros2_sdk::skeleton {

class FixedTargetCatalog final {
public:
  std::optional<geometry_msgs::msg::PoseStamped> resolve(const std::string& target_name) const;
};

}  // namespace ros2_sdk::skeleton

#endif  // ROS2_SDK__FIXED_TARGET_CATALOG_HPP_
