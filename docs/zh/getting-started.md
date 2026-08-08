# 快速入门

> 第一阶段 —— 基础建设。开发环境正在搭建中，以下步骤将随构建流水线落地后完善。

## 前置条件

- 已安装 Docker 及 Compose 插件（Docker Engine 24+）
- 约 10 GB 可用磁盘空间（ROS 2 Jazzy + Gazebo 镜像体积较大）

## 克隆仓库

```bash
git clone git@github.com:200166shang/ros-sdk.git
cd ros-sdk
```

## 启动开发环境

构建镜像并启动容器：

```bash
docker compose -f docker/compose.yaml build
docker compose -f docker/compose.yaml up -d
```

用浏览器打开 <http://localhost:6080> 的 VNC 查看器，即可观察容器内的显示画面。

## 编译工作空间

进入容器并使用 colcon 编译：

```bash
docker compose -f docker/compose.yaml exec ros2 bash

# 容器内
cd /workspace
conan install . --output-folder=build/conan   # 拉取 C++ 依赖（Conan）
colcon build
```

## 运行测试

```bash
# 容器内
colcon test --event-handlers console_cohesion+
```

## 常用命令

```bash
# 停止环境
docker compose -f docker/compose.yaml down

# Dockerfile 变更后重新构建镜像
docker compose -f docker/compose.yaml build
```

## 下一步

- [仓库总览](../README.md)
