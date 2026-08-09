#include <gtest/gtest.h>

#include <memory>
#include <ros2_sdk/error.hpp>
#include <ros2_sdk/result.hpp>
#include <stdexcept>
#include <string>
#include <utility>

namespace ros2_sdk {
namespace {

TEST(ResultTest, StoresSuccessfulValue) {
  const auto result = Result<int>::success(42);

  EXPECT_TRUE(result.has_value());
  EXPECT_TRUE(static_cast<bool>(result));
  EXPECT_EQ(result.value(), 42);
}

TEST(ResultTest, StoresFailureError) {
  const auto result =
      Result<int>::failure(Error(ErrorCode::kInvalidArgument, "request is invalid"));

  EXPECT_FALSE(result.has_value());
  EXPECT_FALSE(static_cast<bool>(result));
  EXPECT_EQ(result.error().code(), ErrorCode::kInvalidArgument);
  EXPECT_EQ(result.error().message(), "request is invalid");
}

TEST(ResultTest, PreservesErrorWhenPropagated) {
  const Error original(ErrorCode::kCommunicationTimeout, "service timed out");
  const auto result = Result<std::string>::failure(original);

  EXPECT_EQ(result.error().code(), original.code());
  EXPECT_EQ(result.error().message(), original.message());
}

TEST(ResultTest, SupportsCopyAndMove) {
  auto original = Result<std::string>::success("path");
  auto copy = original;
  auto moved = std::move(copy);

  EXPECT_EQ(original.value(), "path");
  EXPECT_EQ(moved.value(), "path");
}

TEST(ResultTest, SupportsMoveOnlyValues) {
  auto result = Result<std::unique_ptr<int>>::success(std::make_unique<int>(7));

  std::unique_ptr<int> value = std::move(result).value();

  ASSERT_NE(value, nullptr);
  EXPECT_EQ(*value, 7);
}

TEST(ResultTest, ThrowsWhenAccessingValueFromFailure) {
  const auto result = Result<int>::failure(Error(ErrorCode::kUnknown, "failed"));

  EXPECT_THROW(result.value(), std::bad_variant_access);
}

TEST(ResultTest, ThrowsWhenAccessingErrorFromSuccess) {
  const auto result = Result<int>::success(42);

  EXPECT_THROW(result.error(), std::bad_variant_access);
}

TEST(ResultVoidTest, RepresentsSuccessfulOperation) {
  const auto result = Result<void>::success();

  EXPECT_TRUE(result.has_value());
  EXPECT_TRUE(static_cast<bool>(result));
}

TEST(ResultVoidTest, RepresentsFailedOperation) {
  const auto result =
      Result<void>::failure(Error(ErrorCode::kNotInitialized, "manager is not initialized"));

  EXPECT_FALSE(result.has_value());
  EXPECT_EQ(result.error().code(), ErrorCode::kNotInitialized);
  EXPECT_EQ(result.error().message(), "manager is not initialized");
}

TEST(ResultVoidTest, ThrowsWhenAccessingValueFromFailure) {
  const auto result = Result<void>::failure(Error(ErrorCode::kUnknown, "failed"));

  EXPECT_THROW(result.value(), std::bad_variant_access);
}

TEST(ResultVoidTest, ThrowsWhenAccessingErrorFromSuccess) {
  const auto result = Result<void>::success();

  EXPECT_THROW(result.error(), std::bad_variant_access);
}

}  // namespace
}  // namespace ros2_sdk
