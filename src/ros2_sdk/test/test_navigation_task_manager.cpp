#include <gtest/gtest.h>

#include <memory>
#include <vector>

#include "navigation_task_manager.hpp"

namespace ros2_sdk::skeleton {

class RecordingAdapter final : public NavigationAdapter {
public:
  RecordingAdapter()
      : NavigationAdapter([this](const NavigationAdapterEvent& event) { last_event_ = event; }) {}

  void start(const NavigationTask& task) override { started_task_ = task; }
  void cancel(const std::string& task_id) override {
    canceled_task_id_ = task_id;
    ++cancel_calls_;
  }
  bool action_server_ready(std::chrono::milliseconds /*timeout*/) override { return true; }

  NavigationTask started_task_;
  std::string canceled_task_id_;
  int cancel_calls_{0};
  NavigationAdapterEvent last_event_;
};

TEST(NavigationTaskManagerTest, EnforcesLifecycleAndPublishesEvents) {
  auto hub = std::make_shared<TaskEventHub>();
  auto subscription = hub->subscribe();
  NavigationTaskManager manager(hub);

  const auto task = manager.create("pickup_a");
  TaskEvent event;
  ASSERT_TRUE(subscription->try_pop(&event));
  EXPECT_EQ(event.task.state, TaskState::kAccepted);
  EXPECT_TRUE(manager.transition(task.task_id, TaskState::kRunning, "running"));
  EXPECT_FALSE(manager.transition(task.task_id, TaskState::kAccepted, "backward"));
  const NavigationOutcome outcome{NavigationOutcomeCode::kSucceeded, "done"};
  EXPECT_TRUE(manager.transition(task.task_id, TaskState::kSucceeded, "done", outcome));
  EXPECT_FALSE(manager.transition(task.task_id, TaskState::kSucceeded, "changed", outcome));
  ASSERT_TRUE(manager.get(task.task_id).has_value());
  EXPECT_EQ(manager.get(task.task_id)->state, TaskState::kSucceeded);
  ASSERT_TRUE(manager.get(task.task_id)->outcome.has_value());
  EXPECT_EQ(manager.get(task.task_id)->outcome->code, NavigationOutcomeCode::kSucceeded);
}

TEST(NavigationTaskManagerTest, CancelAcceptedTaskWinsImmediateStartRace) {
  NavigationTaskManager manager;
  const auto task = manager.create("pickup_a");

  ASSERT_EQ(manager.cancel(task.task_id).status, NavigationTaskManager::CancelStatus::kRequested);
  EXPECT_EQ(manager.get(task.task_id)->state, TaskState::kCanceling);
  EXPECT_FALSE(manager.transition(task.task_id, TaskState::kRunning, "late goal response"));
  EXPECT_TRUE(manager.transition(task.task_id, TaskState::kCanceled, "canceled",
                                 NavigationOutcome{NavigationOutcomeCode::kCanceled, "canceled"}));
}

TEST(NavigationTaskManagerTest, AllowsCancelSuccessRaceToSucceed) {
  NavigationTaskManager manager;
  const auto task = manager.create("pickup_a");
  ASSERT_EQ(manager.transition(task.task_id, TaskState::kRunning, "running"), true);
  ASSERT_EQ(manager.cancel(task.task_id).status, NavigationTaskManager::CancelStatus::kRequested);

  manager.handle_adapter_event(NavigationAdapterEvent{
      task.task_id, NavigationAdapterEventKind::kResult, NavigationResultCode::kSucceeded,
      "Nav2 goal succeeded", "",
      NavigationOutcome{NavigationOutcomeCode::kSucceeded, "Nav2 goal succeeded"}});

  ASSERT_TRUE(manager.get(task.task_id).has_value());
  EXPECT_EQ(manager.get(task.task_id)->state, TaskState::kSucceeded);
  EXPECT_EQ(manager.get(task.task_id)->outcome->code, NavigationOutcomeCode::kSucceeded);
}

TEST(NavigationTaskManagerTest, GoalRejectedAfterCancelBecomesCanceled) {
  NavigationTaskManager manager;
  const auto task = manager.create("pickup_a");
  ASSERT_EQ(manager.cancel(task.task_id).status, NavigationTaskManager::CancelStatus::kRequested);

  manager.handle_adapter_event(NavigationAdapterEvent{
      task.task_id, NavigationAdapterEventKind::kGoalRejected, NavigationResultCode::kUnknown,
      "Nav2 rejected the goal", "",
      NavigationOutcome{NavigationOutcomeCode::kGoalRejected, "Nav2 rejected the goal"}});

  ASSERT_TRUE(manager.get(task.task_id).has_value());
  EXPECT_EQ(manager.get(task.task_id)->state, TaskState::kCanceled);
  EXPECT_EQ(manager.get(task.task_id)->outcome->code, NavigationOutcomeCode::kCanceled);
}

TEST(NavigationTaskManagerTest, RejectsUnsolicitedCanceledResult) {
  NavigationTaskManager manager;
  const auto task = manager.create("pickup_a");
  ASSERT_TRUE(manager.transition(task.task_id, TaskState::kRunning, "running"));

  manager.handle_adapter_event(NavigationAdapterEvent{
      task.task_id, NavigationAdapterEventKind::kResult, NavigationResultCode::kCanceled,
      "Nav2 goal was canceled", "",
      NavigationOutcome{NavigationOutcomeCode::kCanceled, "Nav2 goal was canceled"}});

  EXPECT_EQ(manager.get(task.task_id)->state, TaskState::kFailed);
  EXPECT_EQ(manager.get(task.task_id)->outcome->code, NavigationOutcomeCode::kFailed);
}

TEST(NavigationTaskManagerTest, CancelIsIdempotentForCancelingAndCanceled) {
  auto manager = std::make_shared<NavigationTaskManager>();
  auto adapter = std::make_shared<RecordingAdapter>();
  manager->set_adapter(adapter);
  const auto task = manager->start("pickup_a");

  EXPECT_EQ(manager->cancel(task.task_id).status, NavigationTaskManager::CancelStatus::kRequested);
  EXPECT_EQ(manager->cancel(task.task_id).status,
            NavigationTaskManager::CancelStatus::kAlreadyCanceling);
  EXPECT_EQ(adapter->cancel_calls_, 1);

  ASSERT_TRUE(manager->transition(task.task_id, TaskState::kCanceled, "canceled",
                                  NavigationOutcome{NavigationOutcomeCode::kCanceled, "canceled"}));
  EXPECT_EQ(manager->cancel(task.task_id).status,
            NavigationTaskManager::CancelStatus::kAlreadyCanceled);
  EXPECT_EQ(adapter->cancel_calls_, 1);
}

TEST(NavigationTaskManagerTest, PublishesFeedbackWithoutChangingLifecycle) {
  auto hub = std::make_shared<TaskEventHub>();
  auto subscription = hub->subscribe();
  NavigationTaskManager manager(hub);
  const auto task = manager.create("pickup_a");
  TaskEvent ignored;
  ASSERT_TRUE(subscription->try_pop(&ignored));

  ASSERT_TRUE(manager.update_feedback(task.task_id, "distance_remaining=1.500000"));
  ASSERT_TRUE(subscription->try_pop(&ignored));
  EXPECT_EQ(ignored.kind, TaskEventKind::kFeedback);
  EXPECT_EQ(ignored.task.state, TaskState::kAccepted);
  EXPECT_EQ(manager.get(task.task_id)->feedback, "distance_remaining=1.500000");
}

TEST(NavigationTaskManagerTest, PublishesOrderedLifecycleWithTerminalLast) {
  auto hub = std::make_shared<TaskEventHub>();
  auto subscription = hub->subscribe("navigation-1");
  NavigationTaskManager manager(hub);
  const auto task = manager.create("pickup_a");
  ASSERT_EQ(manager.transition(task.task_id, TaskState::kRunning, "running"), true);
  ASSERT_EQ(manager.cancel(task.task_id).status, NavigationTaskManager::CancelStatus::kRequested);
  ASSERT_TRUE(manager.transition(task.task_id, TaskState::kCanceled, "canceled",
                                 NavigationOutcome{NavigationOutcomeCode::kCanceled, "canceled"}));

  std::vector<TaskState> states;
  TaskEvent event;
  while (subscription->try_pop(&event)) {
    if (event.kind == TaskEventKind::kState) {
      states.push_back(event.task.state);
    }
  }
  ASSERT_EQ(states.size(), 4U);
  EXPECT_EQ(states[0], TaskState::kAccepted);
  EXPECT_EQ(states[1], TaskState::kRunning);
  EXPECT_EQ(states[2], TaskState::kCanceling);
  EXPECT_EQ(states[3], TaskState::kCanceled);
}

}  // namespace ros2_sdk::skeleton
