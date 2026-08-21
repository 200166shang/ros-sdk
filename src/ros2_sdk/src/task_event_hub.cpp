#include "task_event_hub.hpp"

#include <algorithm>
#include <chrono>
#include <utility>
#include <vector>

namespace ros2_sdk::skeleton {

struct TaskEventHub::SubscriptionState {
  explicit SubscriptionState(std::optional<std::string> filter, std::size_t queue_capacity)
      : task_id(std::move(filter)), capacity(queue_capacity) {}

  mutable std::mutex mutex;
  std::condition_variable condition;
  std::deque<TaskEvent> queue;
  std::optional<std::string> task_id;
  std::size_t capacity;
  bool is_closed{false};
};

struct TaskEventHub::HubState {
  std::mutex mutex;
  std::unordered_map<std::size_t, std::weak_ptr<Subscription>> subscriptions;
  std::size_t next_id{1};
  std::size_t default_capacity{64};
  bool is_closed{false};
};

TaskEventHub::Subscription::Subscription(std::shared_ptr<HubState> hub_state, std::size_t id,
                                         std::optional<std::string> task_id, std::size_t capacity)
    : hub_state_(std::move(hub_state)),
      state_(std::make_shared<SubscriptionState>(std::move(task_id), capacity)),
      id_(id) {}

TaskEventHub::Subscription::~Subscription() {
  close();
  if (hub_state_) {
    std::lock_guard<std::mutex> lock(hub_state_->mutex);
    hub_state_->subscriptions.erase(id_);
  }
}

bool TaskEventHub::Subscription::next(TaskEvent* event, const std::function<bool()>& should_stop) {
  std::unique_lock<std::mutex> lock(state_->mutex);
  while (!state_->is_closed && state_->queue.empty()) {
    if (should_stop && should_stop()) {
      return false;
    }
    state_->condition.wait_for(lock, std::chrono::milliseconds(100));
  }
  if (state_->queue.empty()) {
    return false;
  }
  *event = std::move(state_->queue.front());
  state_->queue.pop_front();
  return true;
}

bool TaskEventHub::Subscription::try_pop(TaskEvent* event) {
  std::lock_guard<std::mutex> lock(state_->mutex);
  if (state_->queue.empty()) {
    return false;
  }
  *event = std::move(state_->queue.front());
  state_->queue.pop_front();
  return true;
}

void TaskEventHub::Subscription::push(TaskEvent event) {
  std::lock_guard<std::mutex> lock(state_->mutex);
  if (state_->is_closed) {
    return;
  }
  if (state_->queue.size() >= state_->capacity) {
    const auto feedback = std::find_if(
        state_->queue.begin(), state_->queue.end(),
        [](const TaskEvent& queued) { return queued.kind == TaskEventKind::kFeedback; });
    if (feedback != state_->queue.end()) {
      state_->queue.erase(feedback);
    } else {
      return;
    }
  }
  state_->queue.push_back(std::move(event));
  state_->condition.notify_one();
}

std::size_t TaskEventHub::Subscription::size() const {
  std::lock_guard<std::mutex> lock(state_->mutex);
  return state_->queue.size();
}

std::size_t TaskEventHub::Subscription::capacity() const {
  std::lock_guard<std::mutex> lock(state_->mutex);
  return state_->capacity;
}

void TaskEventHub::Subscription::close() {
  std::lock_guard<std::mutex> lock(state_->mutex);
  if (!state_->is_closed) {
    state_->is_closed = true;
    state_->condition.notify_all();
  }
}

bool TaskEventHub::Subscription::closed() const {
  std::lock_guard<std::mutex> lock(state_->mutex);
  return state_->is_closed;
}

TaskEventHub::TaskEventHub(std::size_t default_capacity) : state_(std::make_shared<HubState>()) {
  constexpr std::size_t kMinimumLifecycleCapacity = 4;
  state_->default_capacity = std::max(kMinimumLifecycleCapacity, default_capacity);
}

TaskEventHub::~TaskEventHub() {
  shutdown();
}

TaskEventHub::SubscriptionPtr TaskEventHub::subscribe(const std::string& task_id) {
  std::lock_guard<std::mutex> lock(state_->mutex);
  if (state_->is_closed) {
    return nullptr;
  }
  const std::size_t id = state_->next_id++;
  std::optional<std::string> filter;
  if (!task_id.empty()) {
    filter = task_id;
  }
  auto subscription = std::shared_ptr<Subscription>(
      new Subscription(state_, id, std::move(filter), state_->default_capacity));
  state_->subscriptions.emplace(id, subscription);
  return subscription;
}

void TaskEventHub::publish(TaskEvent event) {
  std::vector<SubscriptionPtr> subscriptions;
  {
    std::lock_guard<std::mutex> lock(state_->mutex);
    if (state_->is_closed) {
      return;
    }
    for (auto iterator = state_->subscriptions.begin(); iterator != state_->subscriptions.end();) {
      if (auto subscription = iterator->second.lock()) {
        subscriptions.push_back(std::move(subscription));
        ++iterator;
      } else {
        iterator = state_->subscriptions.erase(iterator);
      }
    }
  }
  for (const auto& subscription : subscriptions) {
    bool matches = true;
    {
      std::lock_guard<std::mutex> lock(subscription->state_->mutex);
      matches = !subscription->state_->task_id.has_value() ||
                *subscription->state_->task_id == event.task.task_id;
    }
    if (matches) {
      subscription->push(event);
    }
  }
}

void TaskEventHub::shutdown() {
  std::vector<SubscriptionPtr> subscriptions;
  {
    std::lock_guard<std::mutex> lock(state_->mutex);
    if (state_->is_closed) {
      return;
    }
    state_->is_closed = true;
    for (const auto& [id, weak_subscription] : state_->subscriptions) {
      if (auto subscription = weak_subscription.lock()) {
        subscriptions.push_back(std::move(subscription));
      }
    }
    state_->subscriptions.clear();
  }
  for (const auto& subscription : subscriptions) {
    subscription->close();
  }
}

}  // namespace ros2_sdk::skeleton
