#include <gtest/gtest.h>

#include <chrono>
#include <memory>
#include <utility>
#include <vector>

#include "delivery_service.hpp"

namespace {

namespace delivery = ros2_sdk::delivery;

class FakeNavigation final : public ros2_sdk::NavigationPort {
public:
  bool ready(std::chrono::milliseconds /*timeout*/) const override { return true; }

  void navigate(const geometry_msgs::msg::PoseStamped& target,
                FeedbackCallback /*feedback_callback*/, ResultCallback result_callback) override {
    targets.push_back(target);
    result_callback_ = std::move(result_callback);
  }

  void cancel() override { ++cancel_count_; }

  void succeed() {
    ASSERT_TRUE(static_cast<bool>(result_callback_));
    const auto result_callback = result_callback_;
    result_callback_ = {};
    result_callback(NavigationPort::Outcome::kSucceeded);
  }

  std::size_t navigation_count() const { return targets.size(); }
  std::size_t cancel_count() const { return cancel_count_; }

  void cancel_succeed() {
    ASSERT_TRUE(static_cast<bool>(result_callback_));
    const auto result_callback = result_callback_;
    result_callback_ = {};
    result_callback(NavigationPort::Outcome::kCanceled);
  }

  std::vector<geometry_msgs::msg::PoseStamped> targets;

private:
  ResultCallback result_callback_;
  std::size_t cancel_count_{0};
};

delivery::CreateDeliveryRequest make_create_request() {
  delivery::CreateDeliveryRequest request;
  request.set_request_id("request-1");
  request.set_pickup_location("pickup_a");
  request.set_dropoff_location("dropoff_a");
  return request;
}

delivery::ConfirmDeliveryRequest make_confirm_request(const std::string& task_id) {
  delivery::ConfirmDeliveryRequest request;
  request.set_task_id(task_id);
  return request;
}

delivery::CancelDeliveryRequest make_cancel_request(const std::string& task_id) {
  delivery::CancelDeliveryRequest request;
  request.set_task_id(task_id);
  return request;
}

TEST(DeliveryServiceTest, CompletesTheTwoLegDeliveryWithConfirmations) {
  auto navigation = std::make_shared<FakeNavigation>();
  auto service = std::make_shared<ros2_sdk::DeliveryService>(navigation);

  auto create_request = make_create_request();
  delivery::DeliverySnapshot snapshot;
  ASSERT_TRUE(service->CreateDelivery(nullptr, &create_request, &snapshot).ok());
  EXPECT_EQ(snapshot.state(), delivery::STARTING);
  ASSERT_EQ(navigation->navigation_count(), 1U);

  navigation->succeed();
  delivery::GetDeliveryRequest get_request;
  get_request.set_task_id(snapshot.task_id());
  ASSERT_TRUE(service->GetDelivery(nullptr, &get_request, &snapshot).ok());
  EXPECT_EQ(snapshot.state(), delivery::AWAITING_PICKUP_CONFIRMATION);

  const auto task_id = snapshot.task_id();
  auto pickup_confirmation = make_confirm_request(task_id);
  ASSERT_TRUE(service->ConfirmPickup(nullptr, &pickup_confirmation, &snapshot).ok());
  EXPECT_EQ(snapshot.state(), delivery::NAVIGATING_TO_DROPOFF);
  EXPECT_EQ(snapshot.current_target(), "dropoff_a");
  ASSERT_EQ(navigation->navigation_count(), 2U);
  EXPECT_DOUBLE_EQ(navigation->targets.back().pose.position.x, -1.5);
  EXPECT_DOUBLE_EQ(navigation->targets.back().pose.position.y, -1.5);

  navigation->succeed();
  ASSERT_TRUE(service->GetDelivery(nullptr, &get_request, &snapshot).ok());
  EXPECT_EQ(snapshot.state(), delivery::AWAITING_DROPOFF_CONFIRMATION);

  auto dropoff_confirmation = make_confirm_request(task_id);
  ASSERT_TRUE(service->ConfirmDropoff(nullptr, &dropoff_confirmation, &snapshot).ok());
  EXPECT_EQ(snapshot.state(), delivery::COMPLETED);
  EXPECT_TRUE(snapshot.current_target().empty());

  ASSERT_TRUE(service->ConfirmDropoff(nullptr, &dropoff_confirmation, &snapshot).ok());
  EXPECT_EQ(snapshot.state(), delivery::COMPLETED);
  EXPECT_EQ(navigation->navigation_count(), 2U);
}

TEST(DeliveryServiceTest, RejectsEarlyConfirmationAndMakesPickupRetrySafe) {
  auto navigation = std::make_shared<FakeNavigation>();
  auto service = std::make_shared<ros2_sdk::DeliveryService>(navigation);

  auto create_request = make_create_request();
  delivery::DeliverySnapshot snapshot;
  ASSERT_TRUE(service->CreateDelivery(nullptr, &create_request, &snapshot).ok());
  const auto task_id = snapshot.task_id();

  auto pickup_confirmation = make_confirm_request(task_id);
  const grpc::Status early_status =
      service->ConfirmPickup(nullptr, &pickup_confirmation, &snapshot);
  EXPECT_EQ(early_status.error_code(), grpc::StatusCode::FAILED_PRECONDITION);
  EXPECT_EQ(early_status.error_message(),
            "INVALID_STATE: pickup confirmation is not valid in the current delivery state");

  navigation->succeed();
  ASSERT_TRUE(service->ConfirmPickup(nullptr, &pickup_confirmation, &snapshot).ok());
  ASSERT_EQ(navigation->navigation_count(), 2U);

  ASSERT_TRUE(service->ConfirmPickup(nullptr, &pickup_confirmation, &snapshot).ok());
  EXPECT_EQ(snapshot.state(), delivery::NAVIGATING_TO_DROPOFF);
  EXPECT_EQ(navigation->navigation_count(), 2U);
}

TEST(DeliveryServiceTest, RejectsDropoffConfirmationBeforePickupIsConfirmed) {
  auto navigation = std::make_shared<FakeNavigation>();
  auto service = std::make_shared<ros2_sdk::DeliveryService>(navigation);

  auto create_request = make_create_request();
  delivery::DeliverySnapshot snapshot;
  ASSERT_TRUE(service->CreateDelivery(nullptr, &create_request, &snapshot).ok());

  auto dropoff_confirmation = make_confirm_request(snapshot.task_id());
  const grpc::Status status = service->ConfirmDropoff(nullptr, &dropoff_confirmation, &snapshot);
  EXPECT_EQ(status.error_code(), grpc::StatusCode::FAILED_PRECONDITION);
  EXPECT_EQ(status.error_message(),
            "INVALID_STATE: dropoff confirmation is not valid in the current delivery state");
}

TEST(DeliveryServiceTest, KeepsCancelingUntilNavigationConfirmsCancellation) {
  auto navigation = std::make_shared<FakeNavigation>();
  auto service = std::make_shared<ros2_sdk::DeliveryService>(navigation);

  auto create_request = make_create_request();
  delivery::DeliverySnapshot snapshot;
  ASSERT_TRUE(service->CreateDelivery(nullptr, &create_request, &snapshot).ok());

  auto cancel_request = make_cancel_request(snapshot.task_id());
  ASSERT_TRUE(service->CancelDelivery(nullptr, &cancel_request, &snapshot).ok());
  EXPECT_EQ(snapshot.state(), delivery::CANCELING);
  EXPECT_EQ(navigation->cancel_count(), 1U);

  delivery::GetDeliveryRequest get_request;
  get_request.set_task_id(snapshot.task_id());
  ASSERT_TRUE(service->GetDelivery(nullptr, &get_request, &snapshot).ok());
  EXPECT_EQ(snapshot.state(), delivery::CANCELING);

  ASSERT_TRUE(service->CancelDelivery(nullptr, &cancel_request, &snapshot).ok());
  EXPECT_EQ(snapshot.state(), delivery::CANCELING);
  EXPECT_EQ(navigation->cancel_count(), 1U);

  navigation->cancel_succeed();
  ASSERT_TRUE(service->GetDelivery(nullptr, &get_request, &snapshot).ok());
  EXPECT_EQ(snapshot.state(), delivery::CANCELED);

  ASSERT_TRUE(service->CancelDelivery(nullptr, &cancel_request, &snapshot).ok());
  EXPECT_EQ(snapshot.state(), delivery::CANCELED);
  EXPECT_EQ(navigation->cancel_count(), 1U);
}

TEST(DeliveryServiceTest, CancelsWhileWaitingForConfirmationWithoutRobotAction) {
  auto navigation = std::make_shared<FakeNavigation>();
  auto service = std::make_shared<ros2_sdk::DeliveryService>(navigation);

  auto create_request = make_create_request();
  delivery::DeliverySnapshot snapshot;
  ASSERT_TRUE(service->CreateDelivery(nullptr, &create_request, &snapshot).ok());
  navigation->succeed();

  auto cancel_request = make_cancel_request(snapshot.task_id());
  ASSERT_TRUE(service->CancelDelivery(nullptr, &cancel_request, &snapshot).ok());
  EXPECT_EQ(snapshot.state(), delivery::CANCELED);
  EXPECT_EQ(navigation->cancel_count(), 0U);
}

TEST(DeliveryServiceTest, DoesNotCancelCompletedDelivery) {
  auto navigation = std::make_shared<FakeNavigation>();
  auto service = std::make_shared<ros2_sdk::DeliveryService>(navigation);

  auto create_request = make_create_request();
  delivery::DeliverySnapshot snapshot;
  ASSERT_TRUE(service->CreateDelivery(nullptr, &create_request, &snapshot).ok());
  navigation->succeed();

  auto pickup_confirmation = make_confirm_request(snapshot.task_id());
  ASSERT_TRUE(service->ConfirmPickup(nullptr, &pickup_confirmation, &snapshot).ok());
  navigation->succeed();

  auto dropoff_confirmation = make_confirm_request(snapshot.task_id());
  ASSERT_TRUE(service->ConfirmDropoff(nullptr, &dropoff_confirmation, &snapshot).ok());
  EXPECT_EQ(snapshot.state(), delivery::COMPLETED);

  auto cancel_request = make_cancel_request(snapshot.task_id());
  ASSERT_TRUE(service->CancelDelivery(nullptr, &cancel_request, &snapshot).ok());
  EXPECT_EQ(snapshot.state(), delivery::COMPLETED);
  EXPECT_EQ(navigation->cancel_count(), 0U);
}

}  // namespace
