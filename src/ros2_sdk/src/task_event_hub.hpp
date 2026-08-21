#ifndef ROS2_SDK__TASK_EVENT_HUB_HPP_
#define ROS2_SDK__TASK_EVENT_HUB_HPP_

#include <condition_variable>
#include <cstddef>
#include <deque>
#include <functional>
#include <memory>
#include <mutex>
#include <optional>
#include <string>
#include <unordered_map>

#include "navigation_task.hpp"

namespace ros2_sdk::skeleton {

class TaskEventHub final {
private:
  struct HubState;
  struct SubscriptionState;

public:
  class Subscription final {
  public:
    ~Subscription();

    Subscription(const Subscription&) = delete;
    Subscription& operator=(const Subscription&) = delete;

    bool next(TaskEvent* event, const std::function<bool()>& should_stop = {});
    bool try_pop(TaskEvent* event);
    void push(TaskEvent event);
    std::size_t size() const;
    std::size_t capacity() const;
    void close();
    bool closed() const;

  private:
    friend class TaskEventHub;
    Subscription(std::shared_ptr<HubState> hub_state, std::size_t id,
                 std::optional<std::string> task_id, std::size_t capacity);

    std::shared_ptr<HubState> hub_state_;
    std::shared_ptr<SubscriptionState> state_;
    std::size_t id_;
  };

  using SubscriptionPtr = std::shared_ptr<Subscription>;

  explicit TaskEventHub(std::size_t default_capacity = 64);
  ~TaskEventHub();

  TaskEventHub(const TaskEventHub&) = delete;
  TaskEventHub& operator=(const TaskEventHub&) = delete;

  SubscriptionPtr subscribe(const std::string& task_id = "");
  void publish(TaskEvent event);
  void shutdown();

private:
  std::shared_ptr<HubState> state_;
};

}  // namespace ros2_sdk::skeleton

#endif  // ROS2_SDK__TASK_EVENT_HUB_HPP_
