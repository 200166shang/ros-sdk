#include <gtest/gtest.h>

#include <chrono>
#include <memory>
#include <string>
#include <thread>
#include <utility>
#include <vector>

#include "delivery_service.hpp"

namespace {

namespace delivery = ros2_sdk::delivery;

class FakeNavigation final : public ros2_sdk::NavigationPort {
public:
  bool ready(std::chrono::milliseconds /*timeout*/) const override { return ready_; }

  void set_ready(bool ready) { ready_ = ready; }

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

  void fail() {
    ASSERT_TRUE(static_cast<bool>(result_callback_));
    const auto result_callback = result_callback_;
    result_callback_ = {};
    result_callback(NavigationPort::Outcome::kFailed);
  }

  void timeout() {
    ASSERT_TRUE(static_cast<bool>(result_callback_));
    const auto result_callback = result_callback_;
    result_callback_ = {};
    result_callback(NavigationPort::Outcome::kTimedOut);
  }

  std::vector<geometry_msgs::msg::PoseStamped> targets;

private:
  bool ready_{true};
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

delivery::CreateDeliveryRequest make_create_request(const std::string& request_id,
                                                    const std::string& pickup_location,
                                                    const std::string& dropoff_location) {
  delivery::CreateDeliveryRequest request;
  request.set_request_id(request_id);
  request.set_pickup_location(pickup_location);
  request.set_dropoff_location(dropoff_location);
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
  EXPECT_DOUBLE_EQ(navigation->targets.back().pose.position.x, 0.48);
  EXPECT_DOUBLE_EQ(navigation->targets.back().pose.position.y, -0.46);

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

TEST(DeliveryServiceTest, RejectsUnknownLocationsBeforeCreatingATask) {
  auto navigation = std::make_shared<FakeNavigation>();
  auto service = std::make_shared<ros2_sdk::DeliveryService>(navigation);

  auto request = make_create_request("invalid-location", "unknown", "dropoff_a");
  delivery::DeliverySnapshot snapshot;
  const grpc::Status status = service->CreateDelivery(nullptr, &request, &snapshot);

  EXPECT_EQ(status.error_code(), grpc::StatusCode::INVALID_ARGUMENT);
  EXPECT_EQ(status.error_message(),
            "INVALID_LOCATION: pickup and dropoff locations must be known fixed locations");
  EXPECT_EQ(navigation->navigation_count(), 0U);

  delivery::GetDeliveryRequest get_request;
  get_request.set_task_id("task-1");
  EXPECT_EQ(service->GetDelivery(nullptr, &get_request, &snapshot).error_code(),
            grpc::StatusCode::NOT_FOUND);
}

TEST(DeliveryServiceTest, RejectsDifferentRequestWhileDeliveryIsActive) {
  auto navigation = std::make_shared<FakeNavigation>();
  auto service = std::make_shared<ros2_sdk::DeliveryService>(navigation);

  auto first_request = make_create_request("request-1", "pickup_a", "dropoff_a");
  delivery::DeliverySnapshot first_snapshot;
  ASSERT_TRUE(service->CreateDelivery(nullptr, &first_request, &first_snapshot).ok());

  auto second_request = make_create_request("request-2", "pickup_a", "dropoff_a");
  delivery::DeliverySnapshot second_snapshot;
  const grpc::Status status = service->CreateDelivery(nullptr, &second_request, &second_snapshot);

  EXPECT_EQ(status.error_code(), grpc::StatusCode::RESOURCE_EXHAUSTED);
  EXPECT_EQ(status.error_message(), "BUSY: an active delivery already occupies the robot");
  EXPECT_EQ(navigation->navigation_count(), 1U);
}

TEST(DeliveryServiceTest, ReusesTaskForAnIdenticalRequestRetry) {
  auto navigation = std::make_shared<FakeNavigation>();
  auto service = std::make_shared<ros2_sdk::DeliveryService>(navigation);

  auto request = make_create_request("retryable", "pickup_a", "dropoff_a");
  delivery::DeliverySnapshot first_snapshot;
  ASSERT_TRUE(service->CreateDelivery(nullptr, &request, &first_snapshot).ok());

  delivery::DeliverySnapshot retry_snapshot;
  ASSERT_TRUE(service->CreateDelivery(nullptr, &request, &retry_snapshot).ok());

  EXPECT_EQ(retry_snapshot.task_id(), first_snapshot.task_id());
  EXPECT_EQ(retry_snapshot.request_id(), "retryable");
  EXPECT_EQ(navigation->navigation_count(), 1U);
}

TEST(DeliveryServiceTest, RejectsRequestIdReuseWithDifferentParameters) {
  auto navigation = std::make_shared<FakeNavigation>();
  auto service = std::make_shared<ros2_sdk::DeliveryService>(navigation);

  auto first_request = make_create_request("conflicting", "pickup_a", "dropoff_a");
  delivery::DeliverySnapshot first_snapshot;
  ASSERT_TRUE(service->CreateDelivery(nullptr, &first_request, &first_snapshot).ok());

  auto conflicting_request = make_create_request("conflicting", "pickup_a", "pickup_a");
  delivery::DeliverySnapshot conflicting_snapshot;
  const grpc::Status status =
      service->CreateDelivery(nullptr, &conflicting_request, &conflicting_snapshot);

  EXPECT_EQ(status.error_code(), grpc::StatusCode::ALREADY_EXISTS);
  EXPECT_EQ(status.error_message(), "CONFLICT: request_id was used with different parameters");
  EXPECT_EQ(navigation->navigation_count(), 1U);
}

TEST(DeliveryServiceTest, AllowsANewRequestAfterThePreviousDeliveryReachesATerminalState) {
  auto navigation = std::make_shared<FakeNavigation>();
  auto service = std::make_shared<ros2_sdk::DeliveryService>(navigation);

  auto first_request = make_create_request("completed", "pickup_a", "dropoff_a");
  delivery::DeliverySnapshot snapshot;
  ASSERT_TRUE(service->CreateDelivery(nullptr, &first_request, &snapshot).ok());
  navigation->succeed();

  auto cancel_request = make_cancel_request(snapshot.task_id());
  ASSERT_TRUE(service->CancelDelivery(nullptr, &cancel_request, &snapshot).ok());
  EXPECT_EQ(snapshot.state(), delivery::CANCELED);

  auto second_request = make_create_request("next-task", "pickup_a", "dropoff_a");
  ASSERT_TRUE(service->CreateDelivery(nullptr, &second_request, &snapshot).ok());
  EXPECT_NE(snapshot.task_id(), "task-1");
  EXPECT_EQ(navigation->navigation_count(), 2U);
}

TEST(DeliveryServiceTest, AcceptsAtMostOneConcurrentDeliveryCreation) {
  auto navigation = std::make_shared<FakeNavigation>();
  auto service = std::make_shared<ros2_sdk::DeliveryService>(navigation);
  auto first_request = make_create_request("concurrent-1", "pickup_a", "dropoff_a");
  auto second_request = make_create_request("concurrent-2", "pickup_a", "dropoff_a");
  delivery::DeliverySnapshot first_snapshot;
  delivery::DeliverySnapshot second_snapshot;
  grpc::Status first_status;
  grpc::Status second_status;

  std::thread first(
      [&] { first_status = service->CreateDelivery(nullptr, &first_request, &first_snapshot); });
  std::thread second(
      [&] { second_status = service->CreateDelivery(nullptr, &second_request, &second_snapshot); });
  first.join();
  second.join();

  const bool first_succeeded = first_status.ok();
  const bool second_succeeded = second_status.ok();
  EXPECT_NE(first_succeeded, second_succeeded);
  EXPECT_EQ(navigation->navigation_count(), 1U);
  EXPECT_TRUE(first_succeeded ? second_status.error_code() == grpc::StatusCode::RESOURCE_EXHAUSTED
                              : first_status.error_code() == grpc::StatusCode::RESOURCE_EXHAUSTED);
}

TEST(DeliveryServiceTest, RejectsCreationWhenNavigationIsNotReady) {
  auto navigation = std::make_shared<FakeNavigation>();
  navigation->set_ready(false);
  auto service = std::make_shared<ros2_sdk::DeliveryService>(navigation);

  auto request = make_create_request("not-ready", "pickup_a", "dropoff_a");
  delivery::DeliverySnapshot snapshot;
  const grpc::Status status = service->CreateDelivery(nullptr, &request, &snapshot);

  EXPECT_EQ(status.error_code(), grpc::StatusCode::FAILED_PRECONDITION);
  EXPECT_EQ(status.error_message(), "NOT_READY: delivery navigation capability is not ready");
  EXPECT_EQ(navigation->navigation_count(), 0U);

  delivery::GetDeliveryRequest get_request;
  get_request.set_task_id("task-1");
  EXPECT_EQ(service->GetDelivery(nullptr, &get_request, &snapshot).error_code(),
            grpc::StatusCode::NOT_FOUND);
}

TEST(DeliveryServiceTest, RecordsUnreachableFailureForAnAcceptedDelivery) {
  auto navigation = std::make_shared<FakeNavigation>();
  auto service = std::make_shared<ros2_sdk::DeliveryService>(navigation);

  auto request = make_create_request("unreachable", "pickup_a", "dropoff_a");
  delivery::DeliverySnapshot snapshot;
  ASSERT_TRUE(service->CreateDelivery(nullptr, &request, &snapshot).ok());
  navigation->fail();

  delivery::GetDeliveryRequest get_request;
  get_request.set_task_id(snapshot.task_id());
  ASSERT_TRUE(service->GetDelivery(nullptr, &get_request, &snapshot).ok());
  EXPECT_EQ(snapshot.state(), delivery::FAILED);
  EXPECT_EQ(snapshot.failure_code(), "UNREACHABLE");
  EXPECT_EQ(snapshot.failure_reason(), "navigation goal did not succeed");
}

TEST(DeliveryServiceTest, RecordsTimeoutFailureForAnAcceptedDelivery) {
  auto navigation = std::make_shared<FakeNavigation>();
  auto service = std::make_shared<ros2_sdk::DeliveryService>(navigation);

  auto request = make_create_request("timeout", "pickup_a", "dropoff_a");
  delivery::DeliverySnapshot snapshot;
  ASSERT_TRUE(service->CreateDelivery(nullptr, &request, &snapshot).ok());
  navigation->timeout();

  delivery::GetDeliveryRequest get_request;
  get_request.set_task_id(snapshot.task_id());
  ASSERT_TRUE(service->GetDelivery(nullptr, &get_request, &snapshot).ok());
  EXPECT_EQ(snapshot.state(), delivery::FAILED);
  EXPECT_EQ(snapshot.failure_code(), "NAVIGATION_TIMEOUT");
  EXPECT_EQ(snapshot.failure_reason(), "navigation exceeded the 30 second time limit");
}

TEST(DeliveryServiceTest, AllowsANewRequestAfterAnUnreachableDeliveryFails) {
  auto navigation = std::make_shared<FakeNavigation>();
  auto service = std::make_shared<ros2_sdk::DeliveryService>(navigation);

  auto first_request = make_create_request("failed", "pickup_a", "dropoff_a");
  delivery::DeliverySnapshot snapshot;
  ASSERT_TRUE(service->CreateDelivery(nullptr, &first_request, &snapshot).ok());
  navigation->fail();

  auto second_request = make_create_request("recovery-request", "pickup_a", "dropoff_a");
  ASSERT_TRUE(service->CreateDelivery(nullptr, &second_request, &snapshot).ok());
  EXPECT_NE(snapshot.task_id(), "task-1");
  EXPECT_EQ(navigation->navigation_count(), 2U);
}

}  // namespace
