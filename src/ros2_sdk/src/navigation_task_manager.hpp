#ifndef ROS2_SDK__NAVIGATION_TASK_MANAGER_HPP_
#define ROS2_SDK__NAVIGATION_TASK_MANAGER_HPP_

#include <chrono>
#include <cstdint>
#include <memory>
#include <mutex>
#include <optional>
#include <string>
#include <unordered_map>

#include "navigation_adapter.hpp"
#include "navigation_task.hpp"
#include "task_event_hub.hpp"

namespace ros2_sdk::skeleton {

class NavigationTaskManager final {
public:
  explicit NavigationTaskManager(
      std::shared_ptr<TaskEventHub> event_hub = std::make_shared<TaskEventHub>());

  NavigationTaskManager(const NavigationTaskManager&) = delete;
  NavigationTaskManager& operator=(const NavigationTaskManager&) = delete;

  void set_adapter(std::shared_ptr<NavigationAdapter> adapter);
  NavigationTask start(const std::string& target_name);
  bool action_server_ready(std::chrono::milliseconds timeout) const;
  NavigationTask create(const std::string& target_name);
  std::optional<NavigationTask> get(const std::string& task_id) const;

  // This is the only API that changes a task state after creation.
  bool transition(const std::string& task_id, TaskState state, std::string message,
                  std::optional<NavigationOutcome> outcome = std::nullopt);

  bool update_feedback(const std::string& task_id, std::string feedback);

  enum class CancelStatus : std::uint8_t {
    kRequested,
    kAlreadyCanceling,
    kAlreadyCanceled,
    kNotFound,
    kTerminal,
  };

  struct CancelResult {
    CancelStatus status{CancelStatus::kNotFound};
    std::optional<NavigationTask> task;
  };

  // Cancellation is idempotent and deliberately handles ACCEPTED before the
  // adapter has received a Nav2 goal response.
  CancelResult cancel(const std::string& task_id);

  void handle_adapter_event(const NavigationAdapterEvent& event);

  std::shared_ptr<TaskEventHub> event_hub() const { return event_hub_; }

private:
  bool transition_locked(NavigationTask& task, TaskState state, std::string message,
                         std::optional<NavigationOutcome> outcome);
  void publish(const NavigationTask& task, TaskEventKind kind = TaskEventKind::kState) const;
  std::shared_ptr<NavigationAdapter> adapter() const;

  mutable std::mutex mutex_;
  std::unordered_map<std::string, NavigationTask> tasks_;
  std::uint64_t next_id_{1};
  std::shared_ptr<TaskEventHub> event_hub_;
  std::shared_ptr<NavigationAdapter> adapter_;
};

}  // namespace ros2_sdk::skeleton

#endif  // ROS2_SDK__NAVIGATION_TASK_MANAGER_HPP_
