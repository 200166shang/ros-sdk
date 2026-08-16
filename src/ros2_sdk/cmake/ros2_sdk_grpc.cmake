function(ros2_sdk_add_grpc_library target proto_file)
  if(NOT TARGET protobuf::protoc)
    message(FATAL_ERROR "protobuf::protoc is required to generate ${proto_file}")
  endif()

  if(NOT TARGET gRPC::grpc_cpp_plugin)
    message(FATAL_ERROR "gRPC::grpc_cpp_plugin is required to generate ${proto_file}")
  endif()

  set(proto_root "${CMAKE_CURRENT_SOURCE_DIR}/proto")
  set(proto_path "${CMAKE_CURRENT_SOURCE_DIR}/${proto_file}")
  get_filename_component(proto_name "${proto_path}" NAME_WE)
  set(generated_dir "${CMAKE_CURRENT_BINARY_DIR}/generated")

  set(generated_sources
      "${generated_dir}/${proto_name}.pb.cc"
      "${generated_dir}/${proto_name}.grpc.pb.cc")
  set(generated_headers
      "${generated_dir}/${proto_name}.pb.h"
      "${generated_dir}/${proto_name}.grpc.pb.h")

  add_custom_command(
    OUTPUT ${generated_sources} ${generated_headers}
    COMMAND ${CMAKE_COMMAND} -E make_directory "${generated_dir}"
    COMMAND protobuf::protoc
      --proto_path=${proto_root}
      --cpp_out=${generated_dir}
      --grpc_out=${generated_dir}
      --plugin=protoc-gen-grpc=$<TARGET_FILE:gRPC::grpc_cpp_plugin>
      ${proto_path}
    DEPENDS "${proto_path}" protobuf::protoc gRPC::grpc_cpp_plugin
    VERBATIM)

  add_library(${target} STATIC ${generated_sources})
  target_include_directories(${target} PUBLIC "${generated_dir}")
  target_link_libraries(${target} PUBLIC gRPC::grpc++ protobuf::libprotobuf)
  set_target_properties(${target} PROPERTIES POSITION_INDEPENDENT_CODE ON)
endfunction()
