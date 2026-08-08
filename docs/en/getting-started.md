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
./rb docker build-image
./rb docker up
```

Point a browser at <http://localhost:6080> to open the VNC viewer and watch
the container's display.

## Build the Workspace

Build the workspace with Conan and colcon:

```bash
./rb build
```

## Run the Tests

```bash
./rb test
```

## Useful Commands

```bash
# stop the environment
./rb docker down

# rebuild the image after Dockerfile changes
./rb docker build-image
```

## Next Steps

- [Repository overview](../../README.md)
