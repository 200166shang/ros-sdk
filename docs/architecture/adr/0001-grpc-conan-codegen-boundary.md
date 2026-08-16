# ADR 0001: gRPC 代码生成边界

## 状态

已接受

## 背景

通信能力需要同时依赖 gRPC C++ 运行时、protobuf 编译器和 gRPC C++ 插件。若由
Docker apt、宿主机工具链和 Conan 分别提供这些组件，容易出现生成代码与链接库版本
不一致。项目还需要让本地容器和 CI 使用同一套依赖解析结果。

## 决策

- 通过 Conan 提供 gRPC、protobuf、`protoc` 和 `grpc_cpp_plugin`。
- `conanfile.txt` 只声明顶层 gRPC 版本；`conan.lock` 锁定完整依赖图和 recipe revision。
- Docker 镜像只固定 Conan 和基础构建工具，不安装 apt 版 gRPC、protobuf 或 protoc。
- CMake 在构建目录生成 protobuf/gRPC C++ 文件；生成物不提交到源码仓库。
- 生成的静态库是独立 target，仅向使用它的测试或未来 bridge 传播 gRPC/protobuf 依赖，
  不污染当前 headers-only 的 `ros2_sdk` 核心 target。

## 后果

源码只需要维护 `.proto` 和生成规则，清理构建目录后可以从锁定的工具链重新生成。
跨架构构建仍由 Conan 根据当前架构选择或构建 package ID，lockfile 不锁死二进制包 ID。
发布不依赖 protoc 的预生成 SDK 如果成为需求，应在发布打包阶段生成 artifact，而不是
将生成文件加入源码。
