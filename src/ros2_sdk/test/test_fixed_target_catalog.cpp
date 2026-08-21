#include <gtest/gtest.h>

#include "fixed_target_catalog.hpp"

namespace ros2_sdk::skeleton {

TEST(FixedTargetCatalogTest, ResolvesPickupAWithStablePose) {
  const FixedTargetCatalog catalog;
  const auto target = catalog.resolve("pickup_a");

  ASSERT_TRUE(target.has_value());
  EXPECT_EQ(target->header.frame_id, "map");
  EXPECT_DOUBLE_EQ(target->pose.position.x, 1.7);
  EXPECT_DOUBLE_EQ(target->pose.position.y, -1.5);
  EXPECT_DOUBLE_EQ(target->pose.orientation.w, 1.0);
}

TEST(FixedTargetCatalogTest, RejectsUnknownTarget) {
  const FixedTargetCatalog catalog;
  EXPECT_FALSE(catalog.resolve("unknown").has_value());
}

}  // namespace ros2_sdk::skeleton
