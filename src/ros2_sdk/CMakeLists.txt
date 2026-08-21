# =============================================================================
# ros2_sdk — ROS2 C++ Robot Runtime Framework
#
# Phase 1 skeleton: the public runtime target plus the first end-to-end
# navigation service.
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

# Public INTERFACE target for the runtime package.
add_library(${PROJECT_NAME} INTERFACE)

target_include_directories(${PROJECT_NAME} INTERFACE
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
  $<INSTALL_INTERFACE:include>)

target_compile_features(${PROJECT_NAME} INTERFACE cxx_std_17)

ament_target_dependencies(${PROJECT_NAME} INTERFACE
  rclcpp rclcpp_action nav2_msgs std_msgs nav_msgs geometry_msgs sensor_msgs tf2
  tf2_geometry_msgs)

install(TARGETS ${PROJECT_NAME}
  EXPORT export_${PROJECT_NAME})

install(DIRECTORY include/ DESTINATION include)

ament_export_targets(export_${PROJECT_NAME} HAS_LIBRARY_TARGET)
ament_export_dependencies(
  rclcpp rclcpp_action nav2_msgs std_msgs nav_msgs geometry_msgs sensor_msgs tf2
  tf2_geometry_msgs)

# Conan's protobuf build tool is versioned (for example, protoc-33.5.0),
# while the ROS image may also provide an older system protoc. Resolve the
# executable from the Conan package before FindProtobuf creates the target.
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
# Conan's CMakeDeps files are generated in the workspace build directory while
# colcon configures this package in a child directory. Keep the package lookup
# deterministic even when the toolchain does not propagate that prefix.
find_package(gRPC CONFIG QUIET PATHS
  "${CMAKE_BINARY_DIR}/.."
  "${CMAKE_BINARY_DIR}"
  NO_DEFAULT_PATH)
if(NOT gRPC_FOUND)
  find_package(gRPC CONFIG REQUIRED)
endif()

include(cmake/ros2_sdk_grpc.cmake)
ros2_sdk_add_grpc_library(ros2_sdk_navigation_proto proto/navigation_smoke.proto)

add_executable(ros2_sdk_server
  src/fixed_target_catalog.cpp
  src/navigation_task.cpp
  src/navigation_task_manager.cpp
  src/nav2_navigation_adapter.cpp
  src/navigation_service.cpp
  src/task_event_hub.cpp
  src/server_main.cpp)
target_include_directories(ros2_sdk_server PRIVATE src include)
target_link_libraries(ros2_sdk_server
  ${PROJECT_NAME}
  ros2_sdk_navigation_proto
  gRPC::grpc++)
ament_target_dependencies(ros2_sdk_server
  rclcpp rclcpp_action nav2_msgs geometry_msgs)
install(TARGETS ros2_sdk_server DESTINATION lib/${PROJECT_NAME})

if(BUILD_TESTING)
  find_package(ament_cmake_gtest REQUIRED)

  ros2_sdk_add_grpc_library(ros2_sdk_grpc_smoke proto/grpc_smoke.proto)

  ament_add_gtest(test_error_model test/test_error_model.cpp)
  target_link_libraries(test_error_model ${PROJECT_NAME})

  ament_add_gtest(test_result test/test_result.cpp)
  target_link_libraries(test_result ${PROJECT_NAME})

  ament_add_gtest(GrpcSmoke test/test_grpc_smoke.cpp)
  target_link_libraries(GrpcSmoke ${PROJECT_NAME} ros2_sdk_grpc_smoke)

  ament_add_gtest(NavigationServiceTest test/test_navigation_service.cpp)
  target_include_directories(NavigationServiceTest PRIVATE src include)
  target_sources(NavigationServiceTest PRIVATE
    src/fixed_target_catalog.cpp
    src/navigation_task.cpp
    src/navigation_task_manager.cpp
    src/nav2_navigation_adapter.cpp
    src/navigation_service.cpp
    src/task_event_hub.cpp)
  target_link_libraries(NavigationServiceTest
    ${PROJECT_NAME}
    ros2_sdk_navigation_proto
    gRPC::grpc++)
  ament_target_dependencies(NavigationServiceTest
    rclcpp rclcpp_action nav2_msgs geometry_msgs)

  ament_add_gtest(NavigationTaskManagerTest test/test_navigation_task_manager.cpp)
  target_include_directories(NavigationTaskManagerTest PRIVATE src include)
  target_sources(NavigationTaskManagerTest PRIVATE
    src/navigation_task.cpp
    src/navigation_task_manager.cpp
    src/task_event_hub.cpp)
  target_link_libraries(NavigationTaskManagerTest ${PROJECT_NAME})

  ament_add_gtest(TaskEventHubTest test/test_task_event_hub.cpp)
  target_include_directories(TaskEventHubTest PRIVATE src include)
  target_sources(TaskEventHubTest PRIVATE src/navigation_task.cpp src/task_event_hub.cpp)
  target_link_libraries(TaskEventHubTest ${PROJECT_NAME})

  ament_add_gtest(FixedTargetCatalogTest test/test_fixed_target_catalog.cpp)
  target_include_directories(FixedTargetCatalogTest PRIVATE src include)
  target_sources(FixedTargetCatalogTest PRIVATE src/fixed_target_catalog.cpp)
  target_link_libraries(FixedTargetCatalogTest ${PROJECT_NAME})
  ament_target_dependencies(FixedTargetCatalogTest geometry_msgs)

endif()

ament_package()
