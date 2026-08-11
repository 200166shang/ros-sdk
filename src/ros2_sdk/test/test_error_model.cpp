#include <gtest/gtest.h>

#include <ros2_sdk/error.hpp>
#include <ros2_sdk/ros_error_adapter.hpp>
#include <utility>

namespace ros2_sdk {
namespace {

TEST(ErrorCodeTest, ExposesStableValuesAndNames) {
  EXPECT_EQ(error_code_value(ErrorCode::kOk), 0U);
  EXPECT_EQ(error_code_value(ErrorCode::kInvalidArgument), 1001U);
  EXPECT_EQ(error_code_value(ErrorCode::kNotInitialized), 1002U);
  EXPECT_EQ(error_code_value(ErrorCode::kCommunicationTimeout), 2001U);
  EXPECT_EQ(error_code_value(ErrorCode::kServiceUnavailable), 2002U);
  EXPECT_EQ(error_code_value(ErrorCode::kModuleStartFailed), 3001U);
  EXPECT_EQ(error_code_value(ErrorCode::kLoggingInitializationFailed), 4001U);

  EXPECT_EQ(error_code_name(ErrorCode::kOk), "OK");
  EXPECT_EQ(error_code_name(ErrorCode::kUnknown), "UNKNOWN");
  EXPECT_EQ(error_code_name(ErrorCode::kInvalidArgument), "INVALID_ARGUMENT");
  EXPECT_EQ(error_code_name(ErrorCode::kNotInitialized), "NOT_INITIALIZED");
  EXPECT_EQ(error_code_name(ErrorCode::kCommunicationTimeout), "COMMUNICATION_TIMEOUT");
  EXPECT_EQ(error_code_name(ErrorCode::kServiceUnavailable), "SERVICE_UNAVAILABLE");
  EXPECT_EQ(error_code_name(ErrorCode::kModuleStartFailed), "MODULE_START_FAILED");
  EXPECT_EQ(error_code_name(ErrorCode::kLoggingInitializationFailed),
            "LOGGING_INITIALIZATION_FAILED");
}

TEST(ErrorCodeTest, PreservesUnknownValues) {
  constexpr auto unknown =
      static_cast<ErrorCode>(0xDEADBEEFU);  // NOLINT(clang-analyzer-optin.core.EnumCastOutOfRange)

  EXPECT_EQ(error_code_value(unknown), 0xDEADBEEFU);
  EXPECT_EQ(error_code_name(unknown), "UNKNOWN");
  EXPECT_FALSE(is_success(unknown));
}

TEST(ErrorCodeTest, OnlyOkIsSuccessful) {
  EXPECT_TRUE(is_success(ErrorCode::kOk));
  EXPECT_FALSE(is_success(ErrorCode::kUnknown));
  EXPECT_FALSE(is_success(ErrorCode::kInvalidArgument));
}

TEST(ErrorTest, StoresCodeAndMessage) {
  const Error error(ErrorCode::kInvalidArgument, "parameter is empty");

  EXPECT_EQ(error.code(), ErrorCode::kInvalidArgument);
  EXPECT_EQ(error.message(), "parameter is empty");
  EXPECT_EQ(error.to_string(), "INVALID_ARGUMENT: parameter is empty");
}

TEST(ErrorTest, FormatsEmptyMessageWithCodeOnly) {
  const Error error(ErrorCode::kUnknown, "");

  EXPECT_EQ(error.to_string(), "UNKNOWN");
}

TEST(ErrorTest, IsCopyableAndMovable) {
  Error original(ErrorCode::kCommunicationTimeout, "service did not respond");
  Error copy = original;
  Error moved = std::move(copy);

  EXPECT_EQ(moved.code(), ErrorCode::kCommunicationTimeout);
  EXPECT_EQ(moved.message(), "service did not respond");
}

TEST(RosErrorAdapterTest, MapsCommonReturnCodes) {
  EXPECT_EQ(error_code_from_rcl(RCL_RET_OK), ErrorCode::kOk);
  EXPECT_EQ(error_code_from_rcl(RCL_RET_INVALID_ARGUMENT), ErrorCode::kInvalidArgument);
  EXPECT_EQ(error_code_from_rcl(RCL_RET_NOT_INIT), ErrorCode::kNotInitialized);
  EXPECT_EQ(error_code_from_rcl(RCL_RET_TIMEOUT), ErrorCode::kCommunicationTimeout);
}

TEST(RosErrorAdapterTest, MapsUnknownReturnCodeSafely) {
  constexpr auto unknown = static_cast<rcl_ret_t>(0x7FFFFFFF);

  EXPECT_EQ(error_code_from_rcl(unknown), ErrorCode::kUnknown);
}

TEST(RosErrorAdapterTest, PreservesErrorMessage) {
  const Error error = error_from_rcl(RCL_RET_TIMEOUT, "waiting for service timed out");

  EXPECT_EQ(error.code(), ErrorCode::kCommunicationTimeout);
  EXPECT_EQ(error.message(), "waiting for service timed out");
}

}  // namespace
}  // namespace ros2_sdk
