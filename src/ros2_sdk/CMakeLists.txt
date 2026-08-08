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
find_package(std_msgs REQUIRED)
find_package(nav_msgs REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(tf2 REQUIRED)
find_package(tf2_geometry_msgs REQUIRED)

# INTERFACE library — headers only for now, src/ sources added in future PRs.
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
  rclcpp std_msgs nav_msgs geometry_msgs sensor_msgs tf2 tf2_geometry_msgs)

if(BUILD_TESTING)
  find_package(ament_cmake_gtest REQUIRED)
endif()

ament_package()
