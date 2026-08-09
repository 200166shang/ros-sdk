#ifndef ROS2_SDK__RESULT_HPP_
#define ROS2_SDK__RESULT_HPP_

#include <ros2_sdk/error.hpp>
#include <type_traits>
#include <utility>
#include <variant>

namespace ros2_sdk {

// Result stores either a successful value or an Error.
template <typename T>
class [[nodiscard]] Result {
  static_assert(!std::is_same_v<std::remove_cv_t<std::remove_reference_t<T>>, Error>,
                "Result<T> cannot use Error as its value type");

public:
  static Result success(T value) { return Result(std::move(value)); }

  static Result failure(Error error) { return Result(std::move(error)); }

  bool has_value() const noexcept { return std::holds_alternative<T>(storage_); }

  explicit operator bool() const noexcept { return has_value(); }

  T& value() & { return std::get<T>(storage_); }

  const T& value() const& { return std::get<T>(storage_); }

  T&& value() && { return std::get<T>(std::move(storage_)); }

  Error& error() & { return std::get<Error>(storage_); }

  const Error& error() const& { return std::get<Error>(storage_); }

  Error&& error() && { return std::get<Error>(std::move(storage_)); }

private:
  explicit Result(T value) : storage_(std::move(value)) {}

  explicit Result(Error error) : storage_(std::move(error)) {}

  std::variant<T, Error> storage_;
};

// Result<void> stores either success or an Error.
template <>
class [[nodiscard]] Result<void> {
public:
  static Result success() { return Result(); }

  static Result failure(Error error) { return Result(std::move(error)); }

  bool has_value() const noexcept { return std::holds_alternative<std::monostate>(storage_); }

  explicit operator bool() const noexcept { return has_value(); }

  void value() const { std::get<std::monostate>(storage_); }

  Error& error() & { return std::get<Error>(storage_); }

  const Error& error() const& { return std::get<Error>(storage_); }

  Error&& error() && { return std::get<Error>(std::move(storage_)); }

private:
  Result() : storage_(std::monostate{}) {}

  explicit Result(Error error) : storage_(std::move(error)) {}

  std::variant<std::monostate, Error> storage_;
};

}  // namespace ros2_sdk

#endif  // ROS2_SDK__RESULT_HPP_
