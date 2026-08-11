# =============================================================================
# ros2_sdk — ROS2 C++ Robot Runtime Framework
#
# Phase 1 logging core: portable SDK facade over a private spdlog backend.
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
find_package(spdlog REQUIRED)

add_library(${PROJECT_NAME}
  src/logging/log_manager.cpp
  src/logging/logger.cpp
  src/logging/spdlog_backend.cpp)

target_include_directories(${PROJECT_NAME} PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
  $<INSTALL_INTERFACE:include>)

target_compile_features(${PROJECT_NAME} PUBLIC cxx_std_17)

target_link_libraries(${PROJECT_NAME} PUBLIC spdlog::spdlog)

ament_target_dependencies(${PROJECT_NAME} PUBLIC
  rclcpp std_msgs nav_msgs geometry_msgs sensor_msgs tf2 tf2_geometry_msgs)

install(TARGETS ${PROJECT_NAME}
  EXPORT export_${PROJECT_NAME})

install(DIRECTORY include/ DESTINATION include)

ament_export_targets(export_${PROJECT_NAME} HAS_LIBRARY_TARGET)
ament_export_dependencies(
  spdlog rclcpp std_msgs nav_msgs geometry_msgs sensor_msgs tf2 tf2_geometry_msgs)

if(BUILD_TESTING)
  find_package(ament_cmake_gtest REQUIRED)

  ament_add_gtest(test_error_model test/test_error_model.cpp)
  target_link_libraries(test_error_model ${PROJECT_NAME})

  ament_add_gtest(test_result test/test_result.cpp)
  target_link_libraries(test_result ${PROJECT_NAME})

  ament_add_gtest(test_logging test/logging/logging_test.cpp)
  target_link_libraries(test_logging ${PROJECT_NAME})

  add_executable(logging_benchmark test/logging/logging_benchmark.cpp)
  target_link_libraries(logging_benchmark ${PROJECT_NAME})
endif()

ament_package()
