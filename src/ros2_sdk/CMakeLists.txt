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
  find_package(gRPC CONFIG REQUIRED)

  include(cmake/ros2_sdk_grpc.cmake)
  ros2_sdk_add_grpc_library(ros2_sdk_grpc_smoke proto/grpc_smoke.proto)

  ament_add_gtest(test_error_model test/test_error_model.cpp)
  target_link_libraries(test_error_model ${PROJECT_NAME})

  ament_add_gtest(test_result test/test_result.cpp)
  target_link_libraries(test_result ${PROJECT_NAME})

  ament_add_gtest(GrpcSmoke test/test_grpc_smoke.cpp)
  target_link_libraries(GrpcSmoke ${PROJECT_NAME} ros2_sdk_grpc_smoke)
endif()

ament_package()
