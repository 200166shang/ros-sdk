#include <gtest/gtest.h>

#include <string>
#include <utility>
#include <vector>

#include "task_event_hub.hpp"

namespace ros2_sdk::skeleton {

NavigationTask task(const std::string& id, TaskState state, std::string message) {
  return NavigationTask{id, "pickup_a", state, std::move(message), "", std::nullopt};
}

TEST(TaskEventHubTest, DropsFeedbackOnOverflowButKeepsLifecycleAndTerminalEvents) {
  TaskEventHub hub(4);
  const auto subscription = hub.subscribe("task-1");
  ASSERT_EQ(subscription->capacity(), 4U);

  subscription->push(TaskEvent{task("task-1", TaskState::kAccepted, "accepted")});
  subscription->push(TaskEvent{task("task-1", TaskState::kRunning, "running")});
  subscription->push(TaskEvent{task("task-1", TaskState::kCanceling, "canceling")});
  for (int index = 0; index < 100; ++index) {
    subscription->push(TaskEvent{NavigationTask{"task-1", "pickup_a", TaskState::kCanceling, "",
                                                "feedback-" + std::to_string(index), std::nullopt},
                                 TaskEventKind::kFeedback});
    EXPECT_LE(subscription->size(), subscription->capacity());
  }
  subscription->push(TaskEvent{task("task-1", TaskState::kCanceled, "canceled")});
  EXPECT_LE(subscription->size(), subscription->capacity());

  std::vector<TaskEvent> events;
  TaskEvent event;
  while (subscription->try_pop(&event)) {
    events.push_back(event);
  }
  ASSERT_EQ(events.size(), 4U);
  EXPECT_EQ(events[0].task.state, TaskState::kAccepted);
  EXPECT_EQ(events[1].task.state, TaskState::kRunning);
  EXPECT_EQ(events[2].task.state, TaskState::kCanceling);
  EXPECT_EQ(events[3].task.state, TaskState::kCanceled);
}

TEST(TaskEventHubTest, FiltersByTaskAndClosesSubscriptions) {
  TaskEventHub hub;
  const auto subscription = hub.subscribe("task-1");
  hub.publish(TaskEvent{task("task-2", TaskState::kRunning, "ignored")});
  EXPECT_FALSE(subscription->try_pop(nullptr));
  hub.publish(TaskEvent{task("task-1", TaskState::kRunning, "running")});
  TaskEvent event;
  ASSERT_TRUE(subscription->try_pop(&event));
  EXPECT_EQ(event.task.task_id, "task-1");
  hub.shutdown();
  EXPECT_TRUE(subscription->closed());
  EXPECT_FALSE(subscription->next(&event));
}

}  // namespace ros2_sdk::skeleton
