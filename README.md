# RosBridge Pro

A C++ robot runtime framework that manages ROS2 module lifecycle, monitors health, recovers from failures, and enables external access.

![Status](https://img.shields.io/badge/status-Phase%201%20%E2%80%94%20Foundation%20(in%20progress)-orange)

## Status

**Phase 1 — Foundation (in progress).** Repository skeleton, build system, and development environment. No runtime code yet.

## Tech Stack

| Layer       | Choice                              |
| ----------- | ----------------------------------- |
| Language    | C++17                               |
| Middleware  | ROS 2 Jazzy (Joints)                |
| Build       | CMake + colcon + Conan              |
| Containers  | Docker / docker compose             |
| License     | Apache 2.0                          |

## Quick Start

> Placeholder — the development environment is being set up. Full setup instructions will land with the Phase 1 build pipeline.

The development environment is Docker-based. Once the image is built:

```bash
docker compose up -d
docker compose exec ros2 bash
```

## Repository Layout

```
packages/ros2_sdk/    ROS2-facing modules (lifecycle, health, recovery)
packages/infra/       Infrastructure primitives (logging, utilities)
```

## License

This project is licensed under the [Apache License 2.0](LICENSE).
