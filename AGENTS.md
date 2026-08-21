# RosBridge Pro

RosBridge Pro 是基于 C++17 和 ROS 2 Jazzy 的机器人运行时框架，负责模块生命周期、
健康监控、故障恢复、模式切换、任务编排、可观测性和外部接入。项目不实现 SLAM、导航
或感知算法，而是让这些模块能够被可靠地管理和协同。

## 开始工作前

修改行为前按以下顺序建立上下文：

1. 阅读 `README.md`，确认项目定位、边界和当前成熟度。
2. 阅读相关 GitHub Issue，以及已有的模块设计或 ADR。
3. 如果当前环境存在本地完整 PRD，可以将其作为补充上下文，但不能假设远程环境也能
   访问。
4. 检查当前代码、测试和工作区状态，区分计划行为与已实现行为。
5. 如果需求、设计、Issue、代码或测试互相冲突，先报告冲突，不要自行选择一种解释。

本文件只保存每次任务都需要遵守的仓库级规则。详细需求放在本地 PRD 或 Issue，长期
技术决策放在对应设计或 ADR；不要把完整文档复制进 `AGENTS.md`。

## Agent skills

### Issue tracker

Specs and implementation tickets are tracked in GitHub Issues. See
`docs/agents/issue-tracker.md`.

### Domain docs

This is a single-context repository. Use `CONTEXT.md` for the domain glossary,
`docs/modules/` for module designs, and `docs/architecture/adr/` for durable architecture
decisions. See `docs/agents/domain.md`.

## 开发命令

在宿主机的仓库根目录通过 `./rb` 启动项目工作流。build、test 和 lint 会在 `ros2` 容器
内执行；Docker 子命令在宿主机管理开发环境。

macOS 使用 Colima 且 Docker socket 尚未配置时执行：

```bash
export DOCKER_HOST=unix://$HOME/.colima/default/docker.sock
```

```bash
./rb docker build-image   # 构建 rosbridge:dev 镜像
./rb docker up            # 启动 ros2 和 novnc 容器
./rb docker down          # 停止容器
./rb build --clean        # 清理后执行 Conan install 和 colcon build
./rb test                 # 执行 colcon test
./rb test --filter Foo    # 只执行匹配 Foo 的测试
./rb lint                 # 执行 clang-format 检查和 clang-tidy
./rb format               # 格式化 C++ 文件
./rb shell                # 进入 ros2 容器
./rb gazebo start         # 启动 Gazebo 和 TurtleBot3
```

开发镜像定义在 `docker/Dockerfile`，构建上下文和 Compose 配置位于仓库根目录的
`docker-compose.yaml`。不要在本文件记录容易漂移的软件补丁版本或 ROS package 数量。

## 开发流程

1. 从最新的 `main` 创建 `feature/<short-description>` 分支。
2. 将修改范围限制在当前需求或 Issue 内。
3. 实现行为时同步增加测试，并更新受影响的长期文档。
4. 根据修改类型执行对应验证。
5. 使用明确文件路径暂存，只包含本次任务文件。
6. 创建目标为 `main` 的 Pull Request，通过检查和审阅后在 GitHub 合入。

除非用户明确要求，不要推送、创建 PR、合并或删除分支，也不要执行其他远程或破坏性
操作。

### 提交规范

使用 Conventional Commits，必要时增加简短 scope：

```text
feat(comm): add Channel<T> class
fix: correct spdlog package name
docs: update project README
build: update Conan dependencies
test: add Channel unit tests
chore: update repository tooling
```

## 完成前验证

所有完成结论必须基于本轮新执行的检查。无法执行的检查要明确说明。

| 修改类型 | 必须验证 |
|----------|----------|
| C++ 源码或公共头文件 | `./rb format`、`./rb build --clean`、`./rb lint`、`./rb test` |
| Python `./rb` CLI | 受影响命令的 `--help`、对应行为检查、`./rb test` |
| 纯文档 | `git diff --check`、验证修改过的链接和文档中的命令 |
| Docker 或依赖环境 | `./rb docker build-image`，然后执行受影响的 build/test 流程 |
| ROS 2 运行时行为 | 单元测试，以及对应容器或 Gazebo 集成场景 |

`./rb format` 会修改 `src/` 下所有匹配的 C++ 文件。如果工作区存在无关 C++ 修改，
不要运行全量格式化，应只格式化本次任务涉及的文件。

## 代码与包规范

- 使用 C++17、Google C++ Style、`.clang-format` 和 100 列限制。
- 静态分析使用 `.clang-tidy` 中的 Google、modernize、performance 和选定 readability 检查。
- 公共头文件放在 `src/ros2_sdk/include/ros2_sdk/`，使用
  `<ros2_sdk/xxx.hpp>` 方式引用。
- 实现放在 `src/ros2_sdk/src/`，gtest 测试放在 `src/ros2_sdk/test/`。
- 公共 API 需要 Doxygen 文档和面向行为的测试。
- ROS 2 依赖声明在 `src/ros2_sdk/package.xml` 和 CMake；非 ROS C++ 依赖声明在
  `conanfile.txt`。
- 模块能够独立安装且拥有不同消费者之前，继续保留在单一 `ros2_sdk` 包中；未来新包作为
  `src/` 下的同级目录。

```text
src/ros2_sdk/          机器人运行时模块所在的单一 ROS 2 包
  include/ros2_sdk/    公共头文件
  src/                 C++ 实现
  test/                gtest 测试
scripts/               ./rb CLI 实现
docker/                Dockerfile 和 entrypoint
docker-compose.yaml    开发环境服务
```

## 审阅规则

Runtime 代码开始实现后，优先检查以下正确性和安全约束：

- 生命周期启动遵循依赖顺序，停止遵循逆依赖顺序。
- 重试和恢复循环有次数上限、可观测，并且不会无限运行。
- 安全关键故障会进入明确的安全状态，而不是静默继续运行。
- 模式切换在执行副作用前验证所有前置条件。
- 错误通过统一错误模型传播，不能只记录日志后吞掉失败。
- 并发回调和共享状态具有明确的所有权和同步策略。

格式问题交给自动化工具，不作为人工审阅的主要意见。

## 权限与边界

- 不要修改 `.gitignore` 中针对 `docs/prd.md`、`docs/landscape-analysis.md`、
  `docs/superpowers/` 和 `docs/feishu/` 的规则，除非用户明确改变该策略。
- 添加生产依赖、修改 Dockerfile apt 包或改变 `colcon` 构建参数前必须询问。
- 保留已有和未跟踪的用户修改；除非明确属于当前任务，不要清理、覆盖、暂存或提交。
- 阅读文件、修改任务范围内的 `src/` 源码，以及运行 `./rb build/test/lint` 属于正常
  开发操作。

## 文档路由

- 公开项目定位、边界和快速开始：`README.md`。
- 完整 PRD：`docs/prd.md`，本地 ignored，仅作为补充上下文。
- 具体任务和验收标准：GitHub Issues。
- 架构决策：`docs/architecture/adr/`，产生首个决策时创建。
- 模块设计：`docs/modules/<capability>/design.md`，实现对应能力前创建。
- 完整调研：`docs/landscape-analysis.md`，本地 ignored，不是规范性来源。
- 临时实施计划：`docs/superpowers/`，本地 ignored，不是权威来源。
- 私有飞书资料：先索取链接，再将持久且非敏感的结论沉淀到 tracked 的设计或 ADR。
