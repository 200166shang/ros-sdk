# RosBridge Pro

一个管理 ROS 2 模块生命周期、健康状态、故障恢复和任务协作的 C++ 机器人运行时框架。

![状态](https://img.shields.io/badge/status-early%20development-orange)

> 🚧 项目处于早期开发阶段，Runtime API 尚未发布，暂不建议用于生产环境。

## 项目目标

机器人通常同时运行底盘、传感器、定位、导航、感知和任务逻辑等多个模块。这些模块存在
启动依赖，也可能出现进程崩溃、数据停发或输出异常。RosBridge Pro 计划提供一套统一的
运行时管理能力：

- 按依赖顺序启动、停止和重启 ROS 2 模块；
- 持续监控模块存活状态、数据质量和系统资源；
- 根据故障等级执行重试、重启、能力降级或安全停止；
- 安全切换手动、自主、急停等机器人运行模式；
- 编排并监控跨导航、感知和业务模块的多步骤任务；
- 向 Web、移动端和云平台提供统一的状态与控制入口。

项目不重新实现 SLAM、导航、控制或感知算法，而是负责让这些现有模块可靠运行并正确
协作。

## 技术栈

| 层级 | 方案 |
|------|------|
| 语言 | C++17 |
| 中间件 | ROS 2 Jazzy Jalisco |
| 构建 | CMake、colcon、Conan |
| 开发环境 | Docker、Docker Compose、Gazebo |
| 许可证 | Apache 2.0 |

## 快速开始

```bash
# 首次安装 CLI 依赖
pip install -r scripts/requirements.txt

# 构建并启动开发环境
./rb docker build-image
./rb docker up

# 编译和测试
./rb build
./rb test

# 使用完毕后停止容器
./rb docker down
```

运行 `./rb --help` 可以查看完整开发命令。

## CI

每个 Pull Request 都会在 Docker 环境中执行 Build、Lint 和 Test。普通源码变更复用
GHCR 中最新的 `ci-main` 镜像；Dockerfile、Conan 或 ROS 依赖变更会在当前 PR 中构建临时
镜像进行验证。环境变更合入 `main` 并通过验证后，GitHub Actions 会更新
`ghcr.io/200166shang/ros-sdk:ci-main`。项目不保存每个 PR 或 commit 的临时镜像。

## 仓库结构

```text
rb                    可执行的 Python 开发 CLI 入口
docker/               Dockerfile 和容器 entrypoint
docker-compose.yaml   本地开发服务
scripts/              Python CLI 实现
src/ros2_sdk/         机器人运行时模块所在的 ROS 2 包
```

## 许可证

本项目采用 [Apache License 2.0](LICENSE) 开源许可证。
