# 阶段一仿真配送验收手册

本文用于从干净的本地开发环境重复验收 RosBridge Pro 阶段一。验收对象是一个运行在
Gazebo 中的 TurtleBot3 Burger：宿主机上的 Python 客户端通过 gRPC 调用容器内的 C++
Runtime，Runtime 再通过 Nav2 驱动机器人移动。

阶段一只使用内存状态，不提供任务持久化。Runtime 重启后，历史任务和未完成任务都会
消失，这是当前阶段的明确边界，不是恢复能力。

本手册使用标准地图中央的两个固定业务地点：`pickup_a=(0.5,-0.5)`、
`dropoff_a=(0.48,-0.46)`。调用方只传地点名称，不需要传坐标；坐标只是说明仿真地图中的
验证位置。

## 1. 你正在验证什么

调用链如下：

```text
宿主机 Python 客户端
        │ gRPC
        ▼
容器内 C++ Runtime :8765
        │ ROS 2 Action
        ▼
Nav2 NavigateToPose
        │
        ▼
Gazebo TurtleBot3 Burger
```

外部客户端只认识配送业务，不需要安装 ROS 2，也不需要直接处理 Topic、Action、Pose 或
QoS。一次正常配送的业务状态顺序是：

```text
STARTING
  → NAVIGATING_TO_PICKUP
  → AWAITING_PICKUP_CONFIRMATION
  → NAVIGATING_TO_DROPOFF
  → AWAITING_DROPOFF_CONFIRMATION
  → COMPLETED
```

取消和失败是另一类终态：

```text
导航中取消：      NAVIGATING_* → CANCELING → CANCELED
导航不可达：      NAVIGATING_* → FAILED (UNREACHABLE)
导航超过 30 秒：  NAVIGATING_* → FAILED (NAVIGATION_TIMEOUT)
```

## 2. 前置条件

宿主机需要 Docker、Docker Compose 和 Python 3。macOS + Colima 如果 Docker socket 未配置，
先执行：

```bash
export DOCKER_HOST=unix://$HOME/.colima/default/docker.sock
```

首次使用或 Dockerfile 发生变化时构建开发镜像：

```bash
pip install -r scripts/requirements.txt
./rb docker build-image
```

## 3. 启动仿真环境

在终端一启动容器：

```bash
./rb docker up
./rb build --clean
```

在终端二启动 Gazebo 和 TurtleBot3：

```bash
./rb gazebo start
```

Gazebo 的图形界面通过 noVNC 提供，在浏览器打开带自适应缩放的页面：

<http://localhost:6080/vnc_auto.html?scale=true>

当前容器的远程桌面是 `1280×800`，而常见浏览器可视区高度小于 800；不带
`scale=true` 时，Gazebo 窗口底部信息可能被裁掉。`scale=true` 会将完整远程画布等比缩放到
可视区内。不要依赖 `resize=true`：当前 noVNC 服务端会返回
`Resize is administratively prohibited`。

如果出现 `WebUtil.fetchJSON is not a function`，先硬刷新浏览器；这通常是旧版 noVNC
前端资源缓存，不是 Gazebo 或 ROS 运行失败。

确认机器人和 ROS 2 已经启动：

```bash
docker compose exec ros2 ros2 node list
docker compose exec ros2 ros2 topic echo /odom --once
```

应能看到 Gazebo/TurtleBot3 相关节点，并收到一条 `/odom` 消息。

### 3.1 最快的底盘移动验证

如果只需要判断“小车是否真的能动”，不要先启动 Nav2，直接通过 Gazebo bridge 发布
`TwistStamped`。当前 bridge 的订阅类型可以检查：

```bash
docker exec ros2 bash -lc \
  "source /opt/ros/jazzy/setup.bash; ros2 topic info /cmd_vel -v"
```

确认订阅类型是 `geometry_msgs/msg/TwistStamped` 后，执行以下命令：

```bash
# 记录移动前位置
docker exec ros2 bash -lc \
  "source /opt/ros/jazzy/setup.bash; \
   ros2 topic echo /odom nav_msgs/msg/Odometry --once"

# 前进 3 秒，然后发送零速度停车
docker exec ros2 bash -lc \
  "source /opt/ros/jazzy/setup.bash; \
   timeout --signal=SIGINT 3s ros2 topic pub --rate 10 /cmd_vel \
   geometry_msgs/msg/TwistStamped \
   '{header: {frame_id: base_link}, twist: {linear: {x: 0.1}, angular: {z: 0.0}}}' \
   >/dev/null; \
   ros2 topic pub --once /cmd_vel geometry_msgs/msg/TwistStamped \
   '{header: {frame_id: base_link}, twist: {linear: {x: 0.0}, angular: {z: 0.0}}}'"

# 再读一次位置；x 或 y 应发生变化
docker exec ros2 bash -lc \
  "source /opt/ros/jazzy/setup.bash; \
   ros2 topic echo /odom nav_msgs/msg/Odometry --once"
```

本轮实际结果：移动前 `odom.pose.pose.position.x≈0.0`，执行命令后
`x≈0.19235`。因此这条命令是当前最适合的“底盘最小冒烟验证”：耗时短、结果可量化，且
不会把底盘验证和 Nav2 定位/规划问题混在一起。它不代表导航链路已经可用；导航验收仍需
继续执行后面的 initial pose、`/navigate_to_pose` 和配送闭环。

## 4. 启动 Nav2 并设置初始位姿

在终端三启动 Nav2：

```bash
docker exec ros2 bash -lc \
  "source /opt/ros/jazzy/setup.bash && \
   export TURTLEBOT3_MODEL=burger && \
   ros2 launch turtlebot3_navigation2 navigation2.launch.py \
   use_sim_time:=True \
   map:=/opt/ros/jazzy/share/turtlebot3_navigation2/map/map.yaml \
   autostart:=True"
```

在终端四发布 TurtleBot3 初始位姿：

```bash
docker exec ros2 bash -lc \
  "source /opt/ros/jazzy/setup.bash; \
   ros2 topic pub --once /initialpose \
   geometry_msgs/msg/PoseWithCovarianceStamped \
   '{header: {frame_id: map}, pose: {pose: {position: {x: 0.5, y: -0.5, z: 0.0}, orientation: {w: 1.0}}, covariance: [0.25, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]}}'"
```

检查 Nav2 的 Action Server 和生命周期：

```bash
docker exec ros2 bash -lc \
  "source /opt/ros/jazzy/setup.bash; \
   ros2 action list | grep navigate_to_pose; \
   ros2 lifecycle get /bt_navigator"
```

预期包含 `/navigate_to_pose`，并显示 `active [3]`。如果看到 AMCL 提示需要 initial pose，
重新执行上一条发布命令。

## 5. 启动 Runtime 和查看健康状态

在终端五启动 C++ Runtime：

```bash
./rb runtime start
```

宿主机直接调用健康检查：

```bash
python3 -m scripts.client health
```

Nav2 正常时，预期结果：

```json
{"alive": true, "delivery_ready": true, "readiness_reason": "delivery capability is ready"}
```

这里的两个字段含义不同：`alive` 表示 Runtime 进程能响应，`delivery_ready` 表示当前
配送能力可以接受新任务。

## 6. 正常配送闭环

### 6.1 创建配送

```bash
python3 -m scripts.client create-delivery \
  --request-id d7-normal-001 \
  --pickup pickup_a \
  --dropoff dropoff_a
```

创建请求被接受后会立即返回任务快照，通常先看到 `STARTING`，随后进入
`NAVIGATING_TO_PICKUP`。保存返回的 `task_id`，下面以 `task-1` 为例。

循环查询任务：

```bash
python3 -m scripts.client get-delivery --task-id task-1
```

重复查询直到：

```json
{"state": "AWAITING_PICKUP_CONFIRMATION", "current_target": "", ...}
```

同时应能在 noVNC 页面看到机器人从初始位姿移动到 `pickup_a`。到达后确认取货：

```bash
python3 -m scripts.client confirm-pickup --task-id task-1
```

预期立即进入 `NAVIGATING_TO_DROPOFF`，随后查询直到：

```json
{"state": "AWAITING_DROPOFF_CONFIRMATION", "current_target": "", ...}
```

此时机器人应已经移动到 `dropoff_a`。确认送达：

```bash
python3 -m scripts.client confirm-dropoff --task-id task-1
```

最终预期：

```json
{
  "task_id": "task-1",
  "state": "COMPLETED",
  "current_target": "",
  "remaining_distance_m": null,
  "failure_code": "",
  "failure_reason": ""
}
```

### 6.2 重复确认和非法确认

对已经完成的任务再次确认送达，应安全返回原来的 `COMPLETED` 快照，不重复触发动作：

```bash
python3 -m scripts.client confirm-dropoff --task-id task-1
```

在尚未到达取货点时发送确认，预期命令失败并显示 `INVALID_STATE`。这是请求被拒绝，
不会改变任务状态。

## 7. 取消配送

重新创建一个配送任务：

```bash
python3 -m scripts.client create-delivery \
  --request-id d7-cancel-001 \
  --pickup pickup_a \
  --dropoff dropoff_a
```

在机器人仍处于 `STARTING` 或 `NAVIGATING_TO_PICKUP` 时取消：

```bash
python3 -m scripts.client cancel-delivery --task-id task-2
```

如果导航已经开始，预期先返回 `CANCELING`，再次查询直到：

```json
{"state": "CANCELED", "current_target": "", ...}
```

noVNC 中机器人应停止继续前往目标点。重复执行取消命令应返回同一个 `CANCELED` 快照。
如果任务已经到达确认点，取消可以直接返回 `CANCELED`；这仍然是合法的取消结果，表示没有
需要等待的 ROS 2 导航动作。

## 8. 请求拒绝、任务失败和安全重试

以下场景用于验证错误语义。请求拒绝不会创建配送任务；任务失败则会保留一个 `FAILED`
快照供查询。

| 场景 | 命令或操作 | 预期结果 |
|------|------------|----------|
| 未知地点 | `create-delivery --pickup unknown --dropoff dropoff_a` | 命令失败，`INVALID_LOCATION`，不创建任务 |
| Nav2 未就绪 | 停止 Nav2 后创建任务 | 命令失败，`NOT_READY`，不创建任务 |
| 已接受任务不可达 | `--pickup unreachable_a --dropoff dropoff_a` | 任务进入 `FAILED / UNREACHABLE` |
| 单段导航超时 | 创建后暂停 Gazebo，等待 30 秒 | 任务进入 `FAILED / NAVIGATION_TIMEOUT` |
| 已有活动任务 | 活动任务期间再次创建不同 request | 命令失败，`BUSY` |
| 相同 request 重试 | 相同 request、地点和参数再次创建 | 返回原 `task_id`，不重复移动 |
| request 冲突 | 相同 request 但更换地点 | 命令失败，`CONFLICT` |

### 8.1 Nav2 未就绪

停止 Nav2 启动终端，然后确认 Runtime 仍存活但配送未就绪：

```bash
python3 -m scripts.client health
python3 -m scripts.client create-delivery \
  --request-id d7-not-ready-001 \
  --pickup pickup_a \
  --dropoff dropoff_a
```

预期健康结果包含 `"alive": true` 和 `"delivery_ready": false`，创建命令失败并显示：

```text
NOT_READY: delivery navigation capability is not ready
```

此时查询一个未创建的任务应得到 `NOT_FOUND`。

### 8.2 不可达目标

重新启动 Nav2 并设置初始位姿后执行：

```bash
python3 -m scripts.client create-delivery \
  --request-id d7-unreachable-001 \
  --pickup unreachable_a \
  --dropoff dropoff_a
python3 -m scripts.client get-delivery --task-id task-1
```

预期任务被接受，然后进入：

```text
FAILED
failure_code=UNREACHABLE
failure_reason=navigation goal did not succeed
```

### 8.3 导航超时

创建一个正常目标后，立即暂停 Gazebo 世界。暂停只停止仿真时间，Runtime 的 30 秒墙钟
超时仍然会运行：

```bash
python3 -m scripts.client create-delivery \
  --request-id d7-timeout-001 \
  --pickup pickup_a \
  --dropoff dropoff_a

docker exec ros2 bash -lc \
  "source /opt/ros/jazzy/setup.bash; \
   gz service -s /world/default/control \
   --reqtype gz.msgs.WorldControl --reptype gz.msgs.Boolean \
   --timeout 2000 --req 'pause: true'"
```

等待至少 30 秒后查询任务，预期得到：

```text
FAILED
failure_code=NAVIGATION_TIMEOUT
failure_reason=navigation exceeded the 30 second time limit
```

恢复仿真：

```bash
docker exec ros2 bash -lc \
  "source /opt/ros/jazzy/setup.bash; \
   gz service -s /world/default/control \
   --reqtype gz.msgs.WorldControl --reptype gz.msgs.Boolean \
   --timeout 2000 --req 'pause: false'"
```

## 9. Runtime 重启边界

阶段一只保存内存状态。停止并重启 Runtime：

```bash
./rb runtime stop
./rb runtime start
python3 -m scripts.client get-delivery --task-id task-1
```

预期返回 `NOT_FOUND`。这证明当前阶段没有伪装成持久化或恢复系统。

## 10. 完整工程验证

在关闭仿真前执行：

```bash
./rb format
./rb build --clean
./rb lint
./rb test
python3 -m unittest discover -s scripts -p 'test_*.py'
./rb ci
```

预期：C++ 和 Python 测试全部通过，`./rb ci` 的 Build、Lint、Test 三段均通过。停止
环境：

```bash
./rb runtime stop
./rb gazebo stop
./rb docker down
```

## 11. 验收记录模板

每次重复验收至少记录以下内容：

| 项目 | 记录内容 |
|------|----------|
| 环境 | commit、OS、Docker/Colima、是否 clean build |
| 启动 | Gazebo、Nav2、initial pose、Runtime 命令 |
| 正常配送 | task_id、状态序列、Gazebo 中移动证据、最终 `COMPLETED` |
| 取消 | `CANCELING → CANCELED`、机器人停止证据 |
| 请求拒绝 | `INVALID_LOCATION`、`NOT_READY`、`BUSY`、`CONFLICT` |
| 任务失败 | `UNREACHABLE`、`NAVIGATION_TIMEOUT` |
| 重启边界 | 重启后 `NOT_FOUND` |
| 自动化 | build、lint、test、Python 测试结果 |

## 12. 本轮实际验收记录

以下结果来自本轮在 `feature/d7-repeatable-phase1-acceptance` 分支的真实运行，不是仅按预期
填写的示例。仿真启动后发布初始位姿 `(0.5,-0.5)`，`ros2 lifecycle get /bt_navigator`
返回 `active [3]`。

### 12.1 正常配送

命令顺序：

```bash
python3 -m scripts.client create-delivery \
  --request-id d7-normal-002 --pickup pickup_a --dropoff dropoff_a
python3 -m scripts.client get-delivery --task-id task-1
python3 -m scripts.client confirm-pickup --task-id task-1
python3 -m scripts.client get-delivery --task-id task-1
python3 -m scripts.client confirm-dropoff --task-id task-1
```

关键返回依次为：

```text
task-1: STARTING
task-1: AWAITING_PICKUP_CONFIRMATION
task-1: NAVIGATING_TO_DROPOFF, current_target=dropoff_a
task-1: AWAITING_DROPOFF_CONFIRMATION
task-1: COMPLETED
```

### 12.2 取消、输入错误和请求语义

本轮实际观察到：

```text
d7-cancel-001: AWAITING_PICKUP_CONFIRMATION → CANCELED
missing_pickup: INVALID_LOCATION
d7-idempotency-001 重复提交相同参数: 复用 task-3
d7-idempotency-001 更换参数: CONFLICT
d7-busy-001: BUSY
```

由于本轮取消时任务已经到达取货确认点，所以没有观察到 `CANCELING` 中间态；导航中的取消
仍应按第 7 节步骤单独验证。

### 12.3 不可达目标和重启边界

不可达任务的实际返回为：

```json
{"task_id":"task-4","state":"FAILED","failure_code":"UNREACHABLE",
 "failure_reason":"navigation goal did not succeed"}
```

Runtime 重启的实际结果为：

```text
停止 Runtime 后 health: UNAVAILABLE
重新启动 Runtime 后查询旧 task-4: NOT_FOUND
```

本轮 `NOT_READY` 的实际结果为：

```json
{"alive":true,"delivery_ready":false,
 "readiness_reason":"delivery capability is not available yet"}
```

随后创建请求返回：

```text
NOT_READY: delivery navigation capability is not ready
```

将初始位姿改到地图左侧、创建正常目标后暂停 Gazebo，等待 30 秒，实际得到：

```json
{"task_id":"task-1","state":"FAILED",
 "failure_code":"NAVIGATION_TIMEOUT",
 "failure_reason":"navigation exceeded the 30 second time limit"}
```
