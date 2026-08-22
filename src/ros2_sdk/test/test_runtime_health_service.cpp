#include <gtest/gtest.h>

#include "runtime_health_service.hpp"

namespace {

TEST(RuntimeHealthServiceTest, ReportsLivenessSeparatelyFromDeliveryReadiness) {
  ros2_sdk::RuntimeHealthService service;
  ros2_sdk::runtime::HealthRequest request;
  ros2_sdk::runtime::HealthResponse response;

  const grpc::Status status = service.Health(nullptr, &request, &response);

  ASSERT_TRUE(status.ok()) << status.error_message();
  EXPECT_TRUE(response.alive());
  EXPECT_FALSE(response.delivery_ready());
  EXPECT_EQ(response.readiness_reason(), "delivery capability is not available yet");
}

}  // namespace
