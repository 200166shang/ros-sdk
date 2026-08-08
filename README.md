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
| Containers  | Docker / docker-compose             |
| License     | Apache 2.0                          |

## Quick Start

```bash
# 1. Install Python CLI dependencies (once)
pip install -r scripts/requirements.txt

# 2. Build the Docker image (once, or when Dockerfile changes)
./rb docker build-image

# 3. Start the development environment
./rb docker up

# 4. Build the project
./rb build

# 5. Open a shell inside the container
./rb shell

# 6. Stop when done
./rb docker down
```

For the full development setup guide, see the project documentation in `docs/`.

## Repository Layout

```
rb                    Development CLI entry point
docker/               Dockerfile and entrypoint
scripts/              CLI implementation (Python, click-based)
docs/                 Documentation
packages/ros2_sdk/    Single ROS2 package containing all runtime modules
```

## License

This project is licensed under the [Apache License 2.0](LICENSE).
