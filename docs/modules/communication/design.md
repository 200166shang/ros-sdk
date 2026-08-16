# 通信模块设计

## 当前范围

Issue #21 只建立 gRPC/protobuf 的可重复构建基础设施和最小 unary RPC smoke test。ROS
Endpoint、QoS、Mock Node 以及领域 gRPC bridge 由 Issue #18 后续子项目分别设计和实现。

## 构建链路

```text
src/ros2_sdk/proto/*.proto
        ↓ Conan lockfile 提供 protoc 和 grpc_cpp_plugin
        ↓ CMake custom command
build/ros2_sdk/generated/*.pb.{h,cc}
build/ros2_sdk/generated/*.grpc.pb.{h,cc}
        ↓ 独立 ros2_sdk_grpc_* target
gRPC/protobuf C++ 编译与链接
```

`src/ros2_sdk/cmake/ros2_sdk_grpc.cmake` 是内部 helper。它要求 Conan 生成的
`protobuf::protoc` 和 `gRPC::grpc_cpp_plugin` target 存在，并将 `.proto` 时间戳、生成
命令、`protoc` 和插件纳入构建依赖。生成文件位于 build 目录，不提交到源码仓库。

## 版本与更新

`conanfile.txt` 固定顶层 gRPC 版本；`conan.lock` 锁定 protobuf、构建工具和全部传递
依赖的版本及 recipe revision。修改直接依赖后，在容器内更新 lockfile：

```bash
conan lock create . --lockfile-out=conan.lock
```

检查 lockfile diff 后，再执行完整的 clean build。构建统一通过：

```bash
conan install . --lockfile=conan.lock --output-folder=build --build=missing
```

构建输出中的 Conan dependency graph 用于追踪实际解析版本；CMake 配置和 smoke test
进一步验证 `protoc`、gRPC 插件、生成代码以及运行时 RPC 彼此匹配。
