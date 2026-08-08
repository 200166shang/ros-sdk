# Getting Started

> Phase 1 — Foundation. The development environment is being set up; these
> steps will be finalized as the build pipeline lands.

## Prerequisites

- Docker with the Compose plugin (Docker Engine 24+)
- About 10 GB of free disk space (the ROS 2 Jazzy + Gazebo image is large)

## Clone the Repository

```bash
git clone git@github.com:200166shang/ros-sdk.git
cd ros-sdk
```

## Start the Development Environment

Build the image and start the containers:

```bash
docker compose -f docker/compose.yaml build
docker compose -f docker/compose.yaml up -d
```

Point a browser at <http://localhost:6080> to open the VNC viewer and watch
the container's display.

## Build the Workspace

Enter the container and build with colcon:

```bash
docker compose -f docker/compose.yaml exec ros2 bash

# inside the container
cd /workspace
conan install . --output-folder=build/conan   # fetch C++ dependencies (Conan)
colcon build
```

## Run the Tests

```bash
# inside the container
colcon test --event-handlers console_cohesion+
```

## Useful Commands

```bash
# stop the environment
docker compose -f docker/compose.yaml down

# rebuild the image after Dockerfile changes
docker compose -f docker/compose.yaml build
```

## Next Steps

- [Repository overview](../README.md)
