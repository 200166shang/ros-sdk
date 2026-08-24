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

### Gazebo/TurtleBot3 容器验证

开发镜像包含 Gazebo 和 TurtleBot3。启动仿真时，Gazebo GUI 会渲染到 noVNC 容器的 X
server，可在浏览器中查看：

```bash
# 终端一：构建并启动容器
./rb docker build-image
./rb docker up

# 终端二：启动 Gazebo 和 TurtleBot3 Burger
./rb gazebo start
```

打开带自适应缩放的 noVNC 页面：
[http://localhost:6080/vnc_auto.html?scale=true](http://localhost:6080/vnc_auto.html?scale=true)，
应能看到完整的 TurtleBot3 Burger 和默认世界。`scale=true` 会把容器的 1280×800 远程画布
缩放到浏览器可视区，避免底部 Gazebo 信息被浏览器裁掉。若浏览器仍显示
`WebUtil.fetchJSON is not a function`，说明
浏览器缓存了旧版 noVNC 前端资源；可先执行硬刷新，或改用
[http://127.0.0.1:6080/vnc_auto.html?scale=true](http://127.0.0.1:6080/vnc_auto.html?scale=true)。另开终端执行最小
ROS 2 检查：

```bash
docker-compose exec ros2 ros2 node list
docker-compose exec ros2 ros2 topic echo /odom --once
```

如果只想确认 Gazebo 中的底盘确实会移动，使用与当前 Gazebo bridge 匹配的
`geometry_msgs/msg/TwistStamped`，不要使用旧教程中的 `Twist`：

```bash
# 记录移动前位置
docker-compose exec ros2 bash -lc \
  "source /opt/ros/jazzy/setup.bash; \
   ros2 topic echo /odom nav_msgs/msg/Odometry --once"

# 以 0.1 m/s 前进 3 秒；timeout 结束后立即发送零速度
docker-compose exec ros2 bash -lc \
  "source /opt/ros/jazzy/setup.bash; \
   timeout --signal=SIGINT 3s ros2 topic pub --rate 10 /cmd_vel \
   geometry_msgs/msg/TwistStamped \
   '{header: {frame_id: base_link}, twist: {linear: {x: 0.1}, angular: {z: 0.0}}}' \
   >/dev/null; \
   ros2 topic pub --once /cmd_vel geometry_msgs/msg/TwistStamped \
   '{header: {frame_id: base_link}, twist: {linear: {x: 0.0}, angular: {z: 0.0}}}'"

# 再读一次位置；x 或 y 应该发生变化
docker-compose exec ros2 bash -lc \
  "source /opt/ros/jazzy/setup.bash; \
   ros2 topic echo /odom nav_msgs/msg/Odometry --once"
```

这条命令只验证“底盘和 Gazebo 通信正常”，不验证 Nav2 规划；验证导航时继续按验收手册
中的 initial pose、Action Server 和配送命令执行。

看到 Gazebo/ROS 节点并收到 `/odom` 消息后，可停止仿真和容器：

```bash
./rb gazebo stop
./rb docker down
```

阶段一完整配送闭环（创建、取货确认、送达确认、取消、失败语义和重启边界）的可重复
验收步骤见[阶段一仿真配送验收手册](docs/phase1-simulation-acceptance.md)。

macOS + Colima 用户如果 Docker socket 未自动配置，先设置
`DOCKER_HOST=unix://$HOME/.colima/default/docker.sock`。noVNC 使用容器内的独立 X server，
不需要宿主机安装 ROS 2 或 Gazebo。

## CI

每个 Pull Request 都会在原生 Linux ARM64 Docker 环境中执行 Build、Lint 和 Test。普通源码
变更复用 GHCR 中最新的 `ci-arm64-main` 镜像；Dockerfile、Conan 或 ROS 依赖变更会在当前
PR 中构建临时镜像进行验证。环境变更合入 `main` 并通过验证后，GitHub Actions 会更新
`ghcr.io/200166shang/ros-sdk:ci-arm64-main`。项目不保存每个 PR 或 commit 的临时镜像。

Dockerfile 提供两个构建目标：本地 Compose 默认使用包含 Gazebo、TurtleBot3 和 ros-gz
的 `dev` 目标；GitHub Actions 使用只包含编译、测试和静态分析依赖的 `ci` 目标。模拟器
环境继续服务本地开发，不作为 CI 镜像的一部分。

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
