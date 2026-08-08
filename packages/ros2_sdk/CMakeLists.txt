# =============================================================================
# ros2_sdk — ROS2-facing modules
#
# Placeholder package for Phase 1. Owns the ROS 2-facing runtime modules:
# module lifecycle management, health monitoring, and failure recovery.
# Public headers will live under include/ros2_sdk/.
# =============================================================================

cmake_minimum_required(VERSION 3.16)

project(ros2_sdk LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# Header-only library skeleton; gains sources in a later phase.
add_library(ros2_sdk INTERFACE)

target_include_directories(ros2_sdk INTERFACE
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
  $<INSTALL_INTERFACE:include>)

target_compile_features(ros2_sdk INTERFACE cxx_std_17)
