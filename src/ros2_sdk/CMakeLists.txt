# =============================================================================
# ros2_sdk — ROS2 C++ Robot Runtime Framework
#
# Phase 1 skeleton: empty INTERFACE library.
# Headers and sources land in include/ros2_sdk/ and src/ in future PRs.
# =============================================================================

cmake_minimum_required(VERSION 3.22)
project(ros2_sdk LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

add_compile_options(-Wall -Wextra -Wpedantic -Werror)

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(rclcpp_action REQUIRED)
find_package(nav2_msgs REQUIRED)
find_package(std_msgs REQUIRED)
find_package(nav_msgs REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(tf2 REQUIRED)
find_package(tf2_geometry_msgs REQUIRED)

# The public package target remains header-only; runtime implementation targets
# are added below for the first end-to-end gRPC capability.
add_library(${PROJECT_NAME} INTERFACE)

target_include_directories(${PROJECT_NAME} INTERFACE
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
  $<INSTALL_INTERFACE:include>)

target_compile_features(${PROJECT_NAME} INTERFACE cxx_std_17)

ament_target_dependencies(${PROJECT_NAME} INTERFACE
  rclcpp std_msgs nav_msgs geometry_msgs sensor_msgs tf2 tf2_geometry_msgs)

install(TARGETS ${PROJECT_NAME}
  EXPORT export_${PROJECT_NAME})

install(DIRECTORY include/ DESTINATION include)

ament_export_targets(export_${PROJECT_NAME} HAS_LIBRARY_TARGET)
ament_export_dependencies(
  rclcpp rclcpp_action nav2_msgs std_msgs nav_msgs geometry_msgs sensor_msgs tf2
  tf2_geometry_msgs)

# Protobuf and gRPC are Conan dependencies rather than ROS package dependencies.
# Generate the runtime contract for the server even when tests are disabled.
find_file(
  ros2_sdk_protobuf_codegen_helper
  NAMES protobuf-conan-protoc-target.cmake
  PATHS ${CMAKE_PREFIX_PATH}
  PATH_SUFFIXES lib/cmake/protobuf
  NO_DEFAULT_PATH)
if(ros2_sdk_protobuf_codegen_helper)
  get_filename_component(ros2_sdk_protobuf_cmake_dir
                         "${ros2_sdk_protobuf_codegen_helper}" DIRECTORY)
  get_filename_component(ros2_sdk_protobuf_package_dir
                         "${ros2_sdk_protobuf_cmake_dir}/../../.." ABSOLUTE)
  file(GLOB ros2_sdk_protoc_candidates
       "${ros2_sdk_protobuf_package_dir}/bin/protoc-[0-9]*")
  list(LENGTH ros2_sdk_protoc_candidates ros2_sdk_protoc_count)
  if(NOT ros2_sdk_protoc_count EQUAL 1)
    message(FATAL_ERROR
            "Expected exactly one Conan protoc executable, found "
            "${ros2_sdk_protoc_count} in ${ros2_sdk_protobuf_package_dir}/bin")
  endif()
  list(GET ros2_sdk_protoc_candidates 0 PROTOC_PROGRAM)
  set(PROTOC_PROGRAM "${PROTOC_PROGRAM}" CACHE FILEPATH
      "Conan protobuf compiler" FORCE)
endif()

find_package(Protobuf MODULE REQUIRED)
find_package(gRPC CONFIG REQUIRED)
include(cmake/ros2_sdk_grpc.cmake)
ros2_sdk_add_grpc_library(ros2_sdk_runtime_health proto/runtime_health.proto)
ros2_sdk_add_grpc_library(ros2_sdk_delivery proto/delivery.proto)

add_library(ros2_sdk_runtime_service STATIC
  src/delivery_service.cpp
  src/runtime_health_service.cpp)
target_include_directories(ros2_sdk_runtime_service PUBLIC src)
target_link_libraries(ros2_sdk_runtime_service
  ros2_sdk_runtime_health
  ros2_sdk_delivery)
ament_target_dependencies(ros2_sdk_runtime_service
  rclcpp rclcpp_action nav2_msgs geometry_msgs)

add_executable(rosbridge_runtime src/runtime_server.cpp)
target_link_libraries(rosbridge_runtime ros2_sdk_runtime_service)
ament_target_dependencies(rosbridge_runtime rclcpp)

install(TARGETS rosbridge_runtime RUNTIME DESTINATION lib/${PROJECT_NAME})

if(BUILD_TESTING)
  find_package(ament_cmake_gtest REQUIRED)
  ros2_sdk_add_grpc_library(ros2_sdk_grpc_smoke proto/grpc_smoke.proto)

  ament_add_gtest(test_error_model test/test_error_model.cpp)
  target_link_libraries(test_error_model ${PROJECT_NAME})

  ament_add_gtest(test_result test/test_result.cpp)
  target_link_libraries(test_result ${PROJECT_NAME})

  ament_add_gtest(GrpcSmoke test/test_grpc_smoke.cpp)
  target_link_libraries(GrpcSmoke ${PROJECT_NAME} ros2_sdk_grpc_smoke)

  ament_add_gtest(RuntimeHealth test/test_runtime_health_service.cpp)
  target_link_libraries(RuntimeHealth ros2_sdk_runtime_service)

  ament_add_gtest(DeliveryService test/test_delivery_service.cpp)
  target_link_libraries(DeliveryService ros2_sdk_runtime_service)
endif()

ament_package()
