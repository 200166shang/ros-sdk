#include <grpcpp/create_channel.h>
#include <grpcpp/server_builder.h>
#include <gtest/gtest.h>

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <functional>
#include <memory>
#include <mutex>
#include <rclcpp/rclcpp.hpp>
#include <rclcpp_action/rclcpp_action.hpp>
#include <string>
#include <thread>
#include <vector>

#include "nav2_navigation_adapter.hpp"
#include "navigation_service.hpp"

namespace {

using ros2_sdk::skeleton::NavigationAdapterEvent;
using ros2_sdk::skeleton::NavigationAdapterEventCallback;
using ros2_sdk::skeleton::NavigationAdapterEventKind;
using ros2_sdk::skeleton::NavigationOutcome;
using ros2_sdk::skeleton::NavigationOutcomeCode;
using ros2_sdk::skeleton::NavigationResultCode;
using ros2_sdk::skeleton::NavigationTask;
using ros2_sdk::skeleton::NavigationTaskManager;
using ros2_sdk::skeleton::TaskState;

class RclcppEnvironment final : public ::testing::Environment {
public:
  void SetUp() override {
    int argc = 0;
    char** argv = nullptr;
    rclcpp::init(argc, argv);
  }

  void TearDown() override { rclcpp::shutdown(); }
};

[[maybe_unused]] const auto* const kRclcppEnvironment =
    ::testing::AddGlobalTestEnvironment(new RclcppEnvironment());

class FakeNavigationAdapter final : public ros2_sdk::skeleton::NavigationAdapter {
public:
  explicit FakeNavigationAdapter(NavigationAdapterEventCallback callback)
      : NavigationAdapter(std::move(callback)) {}

  void start(const NavigationTask& task) override { last_task_ = task; }
  void cancel(const std::string& task_id) override {
    canceled_task_id_ = task_id;
    ++cancel_calls_;
  }
  bool action_server_ready(std::chrono::milliseconds /*timeout*/) override { return ready_; }

  void emit(const NavigationAdapterEvent& event) { emit_event(event); }

  bool ready_{true};
  NavigationTask last_task_;
  std::string canceled_task_id_;
  int cancel_calls_{0};
};

class NavigationServiceTest : public ::testing::Test {
protected:
  void SetUp() override {
    task_manager_ = std::make_shared<NavigationTaskManager>();
    const std::weak_ptr<NavigationTaskManager> weak_manager = task_manager_;
    fake_adapter_ = std::make_shared<FakeNavigationAdapter>(
        [weak_manager](const NavigationAdapterEvent& event) {
          if (const auto manager = weak_manager.lock()) {
            manager->handle_adapter_event(event);
          }
        });
    task_manager_->set_adapter(fake_adapter_);
    service_ = std::make_unique<ros2_sdk::skeleton::NavigationService>(task_manager_);
  }

  std::shared_ptr<NavigationTaskManager> task_manager_;
  std::shared_ptr<FakeNavigationAdapter> fake_adapter_;
  std::unique_ptr<ros2_sdk::skeleton::NavigationService> service_;
};

TEST_F(NavigationServiceTest, StartGetCancelAndWatchUseTaskContract) {
  grpc::ServerBuilder server_builder;
  int selected_port = 0;
  server_builder.AddListeningPort("127.0.0.1:0", grpc::InsecureServerCredentials(), &selected_port);
  server_builder.RegisterService(service_.get());
  const auto grpc_server = server_builder.BuildAndStart();
  ASSERT_NE(grpc_server, nullptr);

  const auto channel = grpc::CreateChannel("127.0.0.1:" + std::to_string(selected_port),
                                           grpc::InsecureChannelCredentials());
  const auto stub = ros2_sdk::api::NavigationRpc::NewStub(channel);
  ros2_sdk::api::StartNavigationRequest start_request;
  start_request.set_target_name("pickup_a");
  ros2_sdk::api::StartNavigationResponse start_response;
  grpc::ClientContext start_context;
  ASSERT_TRUE(stub->StartNavigation(&start_context, start_request, &start_response).ok());
  ASSERT_EQ(start_response.task().state(), ros2_sdk::api::TASK_ACCEPTED);

  ros2_sdk::api::CancelNavigationRequest cancel_request;
  cancel_request.set_task_id(start_response.task().task_id());
  ros2_sdk::api::CancelNavigationResponse cancel_response;
  grpc::ClientContext cancel_context;
  ASSERT_TRUE(stub->CancelNavigation(&cancel_context, cancel_request, &cancel_response).ok());
  EXPECT_EQ(cancel_response.task().state(), ros2_sdk::api::TASK_CANCELING);
  EXPECT_EQ(fake_adapter_->cancel_calls_, 1);

  grpc::ClientContext repeated_cancel_context;
  ros2_sdk::api::CancelNavigationResponse repeated_cancel_response;
  ASSERT_TRUE(
      stub->CancelNavigation(&repeated_cancel_context, cancel_request, &repeated_cancel_response)
          .ok());
  EXPECT_EQ(repeated_cancel_response.task().state(), ros2_sdk::api::TASK_CANCELING);
  EXPECT_EQ(fake_adapter_->cancel_calls_, 1);

  fake_adapter_->emit(
      NavigationAdapterEvent{start_response.task().task_id(), NavigationAdapterEventKind::kResult,
                             NavigationResultCode::kCanceled, "canceled", "",
                             NavigationOutcome{NavigationOutcomeCode::kCanceled, "canceled"}});
  grpc::ClientContext canceled_again_context;
  ros2_sdk::api::CancelNavigationResponse canceled_again_response;
  ASSERT_TRUE(
      stub->CancelNavigation(&canceled_again_context, cancel_request, &canceled_again_response)
          .ok());
  EXPECT_EQ(canceled_again_response.task().state(), ros2_sdk::api::TASK_CANCELED);
  EXPECT_EQ(fake_adapter_->cancel_calls_, 1);

  ros2_sdk::api::GetNavigationRequest get_request;
  get_request.set_task_id(start_response.task().task_id());
  ros2_sdk::api::GetNavigationResponse get_response;
  grpc::ClientContext get_context;
  ASSERT_TRUE(stub->GetNavigation(&get_context, get_request, &get_response).ok());
  EXPECT_EQ(get_response.task().outcome().code(),
            ros2_sdk::api::NavigationOutcome::OUTCOME_CANCELED);
  grpc_server->Shutdown();
}

TEST_F(NavigationServiceTest, SuccessfulTerminalTaskRejectsCancel) {
  const NavigationTask task = task_manager_->start("pickup_a");
  fake_adapter_->emit(
      NavigationAdapterEvent{task.task_id, NavigationAdapterEventKind::kGoalAccepted,
                             NavigationResultCode::kUnknown, "running", "", std::nullopt});
  fake_adapter_->emit(NavigationAdapterEvent{
      task.task_id, NavigationAdapterEventKind::kResult, NavigationResultCode::kSucceeded,
      "succeeded", "", NavigationOutcome{NavigationOutcomeCode::kSucceeded, "succeeded"}});

  ros2_sdk::api::CancelNavigationRequest request;
  request.set_task_id(task.task_id);
  ros2_sdk::api::CancelNavigationResponse response;
  grpc::ServerContext context;
  EXPECT_EQ(service_->CancelNavigation(&context, &request, &response).error_code(),
            grpc::StatusCode::FAILED_PRECONDITION);
  EXPECT_EQ(fake_adapter_->cancel_calls_, 0);
}

TEST_F(NavigationServiceTest, WatchStreamsOrderedStatesAndEndsAfterTerminal) {
  grpc::ServerBuilder server_builder;
  int selected_port = 0;
  server_builder.AddListeningPort("127.0.0.1:0", grpc::InsecureServerCredentials(), &selected_port);
  server_builder.RegisterService(service_.get());
  const auto grpc_server = server_builder.BuildAndStart();
  ASSERT_NE(grpc_server, nullptr);
  const auto channel = grpc::CreateChannel("127.0.0.1:" + std::to_string(selected_port),
                                           grpc::InsecureChannelCredentials());
  const auto stub = ros2_sdk::api::NavigationRpc::NewStub(channel);

  const NavigationTask task = task_manager_->start("pickup_a");
  ros2_sdk::api::WatchNavigationRequest request;
  request.set_task_id(task.task_id);
  grpc::ClientContext watch_context;
  const auto reader = stub->WatchNavigation(&watch_context, request);
  ASSERT_NE(reader, nullptr);

  ros2_sdk::api::NavigationEvent event;
  ASSERT_TRUE(reader->Read(&event));
  EXPECT_EQ(event.task().state(), ros2_sdk::api::TASK_ACCEPTED);
  fake_adapter_->emit(
      NavigationAdapterEvent{task.task_id, NavigationAdapterEventKind::kGoalAccepted,
                             NavigationResultCode::kUnknown, "running", "", std::nullopt});
  ASSERT_TRUE(reader->Read(&event));
  EXPECT_EQ(event.task().state(), ros2_sdk::api::TASK_RUNNING);
  fake_adapter_->emit(NavigationAdapterEvent{
      task.task_id, NavigationAdapterEventKind::kResult, NavigationResultCode::kSucceeded,
      "succeeded", "", NavigationOutcome{NavigationOutcomeCode::kSucceeded, "succeeded"}});
  ASSERT_TRUE(reader->Read(&event));
  EXPECT_EQ(event.task().state(), ros2_sdk::api::TASK_SUCCEEDED);
  EXPECT_FALSE(reader->Read(&event));
  EXPECT_TRUE(reader->Finish().ok());
  grpc_server->Shutdown();
}

TEST_F(NavigationServiceTest, DisconnectingWatchDoesNotStopBackgroundTask) {
  grpc::ServerBuilder server_builder;
  int selected_port = 0;
  server_builder.AddListeningPort("127.0.0.1:0", grpc::InsecureServerCredentials(), &selected_port);
  server_builder.RegisterService(service_.get());
  const auto grpc_server = server_builder.BuildAndStart();
  ASSERT_NE(grpc_server, nullptr);
  const auto channel = grpc::CreateChannel("127.0.0.1:" + std::to_string(selected_port),
                                           grpc::InsecureChannelCredentials());
  const auto stub = ros2_sdk::api::NavigationRpc::NewStub(channel);

  const NavigationTask task = task_manager_->start("pickup_a");
  ros2_sdk::api::WatchNavigationRequest request;
  request.set_task_id(task.task_id);
  grpc::ClientContext watch_context;
  const auto reader = stub->WatchNavigation(&watch_context, request);
  ASSERT_NE(reader, nullptr);
  ros2_sdk::api::NavigationEvent event;
  ASSERT_TRUE(reader->Read(&event));
  watch_context.TryCancel();
  (void)reader->Finish();

  fake_adapter_->emit(
      NavigationAdapterEvent{task.task_id, NavigationAdapterEventKind::kGoalAccepted,
                             NavigationResultCode::kUnknown, "running", "", std::nullopt});
  fake_adapter_->emit(NavigationAdapterEvent{
      task.task_id, NavigationAdapterEventKind::kResult, NavigationResultCode::kSucceeded,
      "succeeded", "", NavigationOutcome{NavigationOutcomeCode::kSucceeded, "succeeded"}});
  ros2_sdk::api::GetNavigationRequest get_request;
  get_request.set_task_id(task.task_id);
  ros2_sdk::api::GetNavigationResponse get_response;
  grpc::ServerContext get_context;
  ASSERT_TRUE(service_->GetNavigation(&get_context, &get_request, &get_response).ok());
  EXPECT_EQ(get_response.task().state(), ros2_sdk::api::TASK_SUCCEEDED);
  grpc_server->Shutdown();
}

TEST_F(NavigationServiceTest, UnknownTaskIsNotFound) {
  ros2_sdk::api::GetNavigationRequest request;
  request.set_task_id("missing");
  ros2_sdk::api::GetNavigationResponse response;
  grpc::ServerContext context;
  EXPECT_EQ(service_->GetNavigation(&context, &request, &response).error_code(),
            grpc::StatusCode::NOT_FOUND);
}

struct ActionServerState {
  bool accept{true};
  bool publish_feedback{true};
  bool finish_success{false};
  std::atomic_bool cancel_received{false};
  std::mutex mutex;
  std::condition_variable condition;
  std::thread worker;

  ~ActionServerState() {
    if (worker.joinable()) {
      worker.join();
    }
  }
};

using TestAdapter = ros2_sdk::skeleton::Nav2NavigationAdapter;
using TestAction = TestAdapter::Action;
using TestGoalHandle = rclcpp_action::ServerGoalHandle<TestAction>;

std::shared_ptr<rclcpp_action::Server<TestAction>> create_action_server(
    const rclcpp::Node::SharedPtr& node, const std::string& name,
    const std::shared_ptr<ActionServerState>& state) {
  return rclcpp_action::create_server<TestAction>(
      node, name,
      [state](const rclcpp_action::GoalUUID&, const std::shared_ptr<const TestAction::Goal>&) {
        return state->accept ? rclcpp_action::GoalResponse::ACCEPT_AND_EXECUTE
                             : rclcpp_action::GoalResponse::REJECT;
      },
      [state](const std::shared_ptr<TestGoalHandle>&) {
        state->cancel_received.store(true);
        state->condition.notify_all();
        return rclcpp_action::CancelResponse::ACCEPT;
      },
      [state](const std::shared_ptr<TestGoalHandle>& goal_handle) {
        state->worker = std::thread([state, goal_handle] {
          std::this_thread::sleep_for(std::chrono::milliseconds(100));
          if (state->publish_feedback) {
            auto feedback = std::make_shared<TestAction::Feedback>();
            feedback->distance_remaining = 1.5F;
            goal_handle->publish_feedback(feedback);
          }
          if (state->finish_success) {
            std::this_thread::sleep_for(std::chrono::milliseconds(100));
            goal_handle->succeed(std::make_shared<TestAction::Result>());
            return;
          }
          std::unique_lock<std::mutex> lock(state->mutex);
          state->condition.wait(lock, [state] { return state->cancel_received.load(); });
          lock.unlock();
          while (rclcpp::ok() && !goal_handle->is_canceling()) {
            std::this_thread::sleep_for(std::chrono::milliseconds(10));
          }
          if (goal_handle->is_canceling()) {
            goal_handle->canceled(std::make_shared<TestAction::Result>());
          }
        });
      });
}

class Nav2NavigationAdapterTest : public ::testing::Test {
protected:
  void start_executor() {
    executor_ =
        std::make_unique<rclcpp::executors::MultiThreadedExecutor>(rclcpp::ExecutorOptions(), 2);
    executor_->add_node(node_);
    executor_thread_ = std::thread([this] { executor_->spin(); });
  }

  void stop_executor() {
    executor_->cancel();
    if (executor_thread_.joinable()) {
      executor_thread_.join();
    }
    executor_->remove_node(node_);
  }

  rclcpp::Node::SharedPtr node_ = std::make_shared<rclcpp::Node>("nav2_navigation_adapter_test");
  std::unique_ptr<rclcpp::executors::MultiThreadedExecutor> executor_;
  std::thread executor_thread_;
};

TEST_F(Nav2NavigationAdapterTest, KeepsAcceptedUntilGoalResponseAndCancelsGoal) {
  const auto state = std::make_shared<ActionServerState>();
  auto action_server = create_action_server(node_, "adapter_cancel_action", state);
  auto manager = std::make_shared<NavigationTaskManager>();
  const std::weak_ptr<NavigationTaskManager> weak_manager = manager;
  auto adapter = std::make_shared<TestAdapter>(
      node_,
      [weak_manager](const NavigationAdapterEvent& event) {
        if (const auto locked = weak_manager.lock()) {
          locked->handle_adapter_event(event);
        }
      },
      std::chrono::seconds(1), "adapter_cancel_action");
  manager->set_adapter(adapter);
  start_executor();

  ASSERT_TRUE(manager->action_server_ready(std::chrono::seconds(5)));
  const NavigationTask task = manager->start("pickup_a");
  EXPECT_EQ(task.state, TaskState::kAccepted);
  for (int attempt = 0; attempt < 100 && manager->get(task.task_id)->state == TaskState::kAccepted;
       ++attempt) {
    std::this_thread::sleep_for(std::chrono::milliseconds(10));
  }
  ASSERT_EQ(manager->get(task.task_id)->state, TaskState::kRunning);
  for (int attempt = 0; attempt < 100 && manager->get(task.task_id)->feedback.empty(); ++attempt) {
    std::this_thread::sleep_for(std::chrono::milliseconds(10));
  }
  EXPECT_EQ(manager->get(task.task_id)->feedback, "distance_remaining=1.500000");
  ASSERT_EQ(manager->cancel(task.task_id).status, NavigationTaskManager::CancelStatus::kRequested);
  for (int attempt = 0; attempt < 100 && !state->cancel_received.load(); ++attempt) {
    std::this_thread::sleep_for(std::chrono::milliseconds(10));
  }
  ASSERT_TRUE(state->cancel_received.load());
  for (int attempt = 0; attempt < 100 && manager->get(task.task_id)->state != TaskState::kCanceled;
       ++attempt) {
    std::this_thread::sleep_for(std::chrono::milliseconds(10));
  }
  ASSERT_EQ(manager->get(task.task_id)->state, TaskState::kCanceled);
  EXPECT_EQ(manager->get(task.task_id)->outcome->code, NavigationOutcomeCode::kCanceled);

  stop_executor();
  action_server.reset();
  adapter.reset();
  manager.reset();
}

TEST_F(Nav2NavigationAdapterTest, GoalRejectionBecomesRejectedOutcome) {
  const auto state = std::make_shared<ActionServerState>();
  state->accept = false;
  auto action_server = create_action_server(node_, "adapter_reject_action", state);
  auto manager = std::make_shared<NavigationTaskManager>();
  const std::weak_ptr<NavigationTaskManager> weak_manager = manager;
  auto adapter = std::make_shared<TestAdapter>(
      node_,
      [weak_manager](const NavigationAdapterEvent& event) {
        if (const auto locked = weak_manager.lock()) {
          locked->handle_adapter_event(event);
        }
      },
      std::chrono::seconds(1), "adapter_reject_action");
  manager->set_adapter(adapter);
  start_executor();

  const NavigationTask task = manager->start("pickup_a");
  for (int attempt = 0; attempt < 100 && manager->get(task.task_id)->state == TaskState::kAccepted;
       ++attempt) {
    std::this_thread::sleep_for(std::chrono::milliseconds(10));
  }
  ASSERT_EQ(manager->get(task.task_id)->state, TaskState::kRejected);
  EXPECT_EQ(manager->get(task.task_id)->outcome->code, NavigationOutcomeCode::kGoalRejected);

  stop_executor();
  action_server.reset();
  adapter.reset();
  manager.reset();
}

TEST_F(Nav2NavigationAdapterTest, SuccessResultBecomesSucceededOutcome) {
  const auto state = std::make_shared<ActionServerState>();
  state->finish_success = true;
  auto action_server = create_action_server(node_, "adapter_success_action", state);
  auto manager = std::make_shared<NavigationTaskManager>();
  const std::weak_ptr<NavigationTaskManager> weak_manager = manager;
  auto adapter = std::make_shared<TestAdapter>(
      node_,
      [weak_manager](const NavigationAdapterEvent& event) {
        if (const auto locked = weak_manager.lock()) {
          locked->handle_adapter_event(event);
        }
      },
      std::chrono::seconds(1), "adapter_success_action");
  manager->set_adapter(adapter);
  start_executor();

  const NavigationTask task = manager->start("pickup_a");
  EXPECT_EQ(task.state, TaskState::kAccepted);
  for (int attempt = 0; attempt < 150 && manager->get(task.task_id)->state != TaskState::kSucceeded;
       ++attempt) {
    std::this_thread::sleep_for(std::chrono::milliseconds(10));
  }
  ASSERT_EQ(manager->get(task.task_id)->state, TaskState::kSucceeded);
  EXPECT_EQ(manager->get(task.task_id)->outcome->code, NavigationOutcomeCode::kSucceeded);

  stop_executor();
  action_server.reset();
  adapter.reset();
  manager.reset();
}

}  // namespace
