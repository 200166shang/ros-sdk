# =============================================================================
# RosBridge Pro — top-level CMake project
#
# The workspace is built with colcon (see the Docker image); this file is the
# single CMake entry point that wires the ROS 2 packages and the project
# packages together, so `colcon build` and `cmake` from the root behave the
# same way.
# =============================================================================

cmake_minimum_required(VERSION 3.16)

project(rosbridge_pro
  VERSION 0.1.0
  DESCRIPTION "A C++ robot runtime framework that manages ROS2 module lifecycle, monitors health, recovers from failures, and enables external access."
  LANGUAGES CXX)

# --- Language standard: C++17 -------------------------------------------------
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# --- Google Style compiler flags ----------------------------------------------
add_compile_options(-Wall -Wextra -Wpedantic -Werror)

# Export compilation database for clang-tidy / IDEs.
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

# --- ROS 2 packages ------------------------------------------------------------
# Requires the ROS 2 environment to be sourced (or CMAKE_PREFIX_PATH set),
# which the Docker image's entrypoint does for us.
find_package(rclcpp REQUIRED)
find_package(std_msgs REQUIRED)
find_package(nav_msgs REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(tf2 REQUIRED)
find_package(tf2_geometry_msgs REQUIRED)

# --- Testing -------------------------------------------------------------------
include(CTest)
if(BUILD_TESTING)
  enable_testing()
endif()

# --- Packages ------------------------------------------------------------------
add_subdirectory(packages/ros2_sdk)
