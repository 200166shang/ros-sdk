#include <grpcpp/create_channel.h>
#include <grpcpp/server_builder.h>
#include <gtest/gtest.h>

#include <atomic>
#include <chrono>
#include <memory>
#include <rclcpp/rclcpp.hpp>
#include <string>
#include <thread>

#include "navigation_action_client.hpp"
#include "navigation_service.hpp"

namespace {

class NavigationServiceTest : public ::testing::Test {
protected:
  static void SetUpTestSuite() {
    int argc = 0;
    char** argv = nullptr;
    rclcpp::init(argc, argv);
  }

  static void TearDownTestSuite() { rclcpp::shutdown(); }

  void SetUp() override {
    node_ = std::make_shared<rclcpp::Node>("navigation_service_test");
    action_client_ = std::make_shared<ros2_sdk::skeleton::NavigationActionClient>(node_);
    service_ = std::make_unique<ros2_sdk::skeleton::NavigationService>(action_client_);
  }

  rclcpp::Node::SharedPtr node_;
  std::shared_ptr<ros2_sdk::skeleton::NavigationActionClient> action_client_;
  std::unique_ptr<ros2_sdk::skeleton::NavigationService> service_;
};

TEST_F(NavigationServiceTest, RejectsUnknownTargetBeforeContactingNav2) {
  grpc::ServerContext context;
  ros2_sdk::skeleton::NavigateRequest request;
  request.set_target_name("unknown");
  ros2_sdk::skeleton::NavigateResponse response;

  const grpc::Status status = service_->Navigate(&context, &request, &response);

  ASSERT_TRUE(status.ok());
  EXPECT_EQ(response.outcome(), ros2_sdk::skeleton::NavigateResponse::INVALID_TARGET);
  EXPECT_FALSE(response.message().empty());
}

TEST_F(NavigationServiceTest, CancelsPendingGoalWhenCallerIsCancelled) {
  using Action = ros2_sdk::skeleton::NavigationActionClient::Action;
  using ServerGoalHandle = rclcpp_action::ServerGoalHandle<Action>;
  using ServerGoalHandlePtr = std::shared_ptr<ServerGoalHandle>;

  constexpr char kTestActionName[] = "navigation_service_test_navigate_to_pose";
  std::atomic_bool cancel_received{false};
  std::shared_ptr<ServerGoalHandle> active_goal;
  const auto action_server = rclcpp_action::create_server<Action>(
      node_, kTestActionName,
      [](const rclcpp_action::GoalUUID&, const std::shared_ptr<const Action::Goal>&) {
        return rclcpp_action::GoalResponse::ACCEPT_AND_EXECUTE;
      },
      [&cancel_received](const ServerGoalHandlePtr&) {
        cancel_received.store(true);
        return rclcpp_action::CancelResponse::ACCEPT;
      },
      [&active_goal](const ServerGoalHandlePtr& goal_handle) { active_goal = goal_handle; });

  const auto action_client = std::make_shared<ros2_sdk::skeleton::NavigationActionClient>(
      node_, std::chrono::seconds(1), kTestActionName);
  ros2_sdk::skeleton::NavigationService service(action_client);

  grpc::ServerBuilder server_builder;
  int selected_port = 0;
  server_builder.AddListeningPort("127.0.0.1:0", grpc::InsecureServerCredentials(), &selected_port);
  server_builder.RegisterService(&service);
  const auto grpc_server = server_builder.BuildAndStart();
  ASSERT_NE(grpc_server, nullptr);

  const auto channel = grpc::CreateChannel("127.0.0.1:" + std::to_string(selected_port),
                                           grpc::InsecureChannelCredentials());
  const auto stub = ros2_sdk::skeleton::NavigationRpc::NewStub(channel);
  grpc::ClientContext context;
  context.set_deadline(std::chrono::system_clock::now() + std::chrono::milliseconds(100));
  ros2_sdk::skeleton::NavigateRequest request;
  request.set_target_name("pickup_a");
  ros2_sdk::skeleton::NavigateResponse response;

  rclcpp::executors::SingleThreadedExecutor executor;
  executor.add_node(node_);
  std::thread executor_thread([&executor] { executor.spin(); });

  if (!action_client->action_server_ready(std::chrono::seconds(5))) {
    grpc_server->Shutdown();
    executor.cancel();
    executor_thread.join();
    executor.remove_node(node_);
    ADD_FAILURE() << "test NavigateToPose action server was not discovered";
    return;
  }

  const grpc::Status status = stub->Navigate(&context, request, &response);

  for (int attempt = 0; attempt < 100 && !cancel_received.load(); ++attempt) {
    std::this_thread::sleep_for(std::chrono::milliseconds(10));
  }
  grpc_server->Shutdown();
  executor.cancel();
  executor_thread.join();
  executor.remove_node(node_);

  EXPECT_EQ(status.error_code(), grpc::StatusCode::DEADLINE_EXCEEDED);
  EXPECT_EQ(response.outcome(), ros2_sdk::skeleton::NavigateResponse::OUTCOME_UNSPECIFIED);
  EXPECT_TRUE(cancel_received.load());
}

}  // namespace
