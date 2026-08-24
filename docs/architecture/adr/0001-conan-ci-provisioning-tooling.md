# Conan CI 凭据配置使用 Python 运维工具

状态：已接受。

Conan CI 访问凭据配置流程由本地 Python 工具负责交互、顺序编排和失败传播，GitHub Actions 只
负责后续的只读 smoke 验证。远程 SSH 运维使用 Fabric，GitHub Secrets、Variables 和 workflow
run 使用 PyGithub，终端展示使用现有 Rich 依赖；保留 `ssh-keyscan` 作为独立的主机指纹采集步骤。
这样可以把一次性维护者操作写成可测试的 Python 阶段，同时保留 host key 拒绝、秘密不落盘和
失败即停止等安全约束。纯 Shell 或 YAML 无法清楚表达这些交互式确认、临时秘密和跨系统副作用。
