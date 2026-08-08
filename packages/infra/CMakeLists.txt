# =============================================================================
# infra — infrastructure primitives
#
# Placeholder package for Phase 1. Owns framework infrastructure that is
# independent of ROS 2: logging, utilities, and other shared primitives.
# Public headers will live under include/infra/.
# =============================================================================

cmake_minimum_required(VERSION 3.16)

project(infra LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# Header-only library skeleton; gains sources in a later phase.
add_library(infra INTERFACE)

target_include_directories(infra INTERFACE
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
  $<INSTALL_INTERFACE:include>)

target_compile_features(infra INTERFACE cxx_std_17)
