# =============================================================================
# RosBridge Pro — ROS2 Robot Runtime Framework
#
# Development image for the RosBridge Pro runtime framework.
#
# Base image: ros:jazzy-ros-core
#   - Ubuntu 24.04 (Noble) with ROS 2 Jazzy core installed
#   - ROS 2 apt repositories already configured, so ros-<distro>-* packages
#     install directly with apt
#
# Layer ordering is deliberate: everything that changes rarely (system and
# ROS 2 packages, Conan) comes first so it stays cached across rebuilds, and
# everything that changes often (source, workspace) comes last.
# =============================================================================

FROM ros:jazzy-ros-core

# -----------------------------------------------------------------------------
# Environment
# -----------------------------------------------------------------------------
ENV DEBIAN_FRONTEND=noninteractive
ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8
ENV ROS_DISTRO=jazzy
ENV RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
ENV TURTLEBOT3_MODEL=burger
ENV WORKSPACE=/workspace

# -----------------------------------------------------------------------------
# System packages
#
# One combined apt layer: apt lists are removed in the same RUN that installs,
# and package installs happen before anything project-specific is copied in,
# maximizing build-cache reuse.
# -----------------------------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        cmake \
        git \
        python3-colcon-common-extensions \
        python3-pip \
        python3-rosdep \
        clang-format \
        clang-tidy \
        ros-${ROS_DISTRO}-gazebo-ros-pkgs \
        ros-${ROS_DISTRO}-rmw-cyclonedds-cpp \
        ros-${ROS_DISTRO}-turtlebot3 \
        ros-${ROS_DISTRO}-turtlebot3-simulations \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# -----------------------------------------------------------------------------
# Conan (C++ package manager)
#
# Ubuntu 24.04 ships an externally-managed Python, so pip requires
# --break-system-packages inside the image. Installed in its own layer so
# future apt changes do not invalidate it (and vice versa).
# -----------------------------------------------------------------------------
RUN python3 -m pip install --no-cache-dir --break-system-packages conan

# -----------------------------------------------------------------------------
# Entrypoint
#
# Sources the ROS 2 environment (and the workspace overlay once built),
# then execs the container command. Placed late: it is copied on every build.
# -----------------------------------------------------------------------------
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]

# -----------------------------------------------------------------------------
# Workspace
#
# The workspace directory is bind-mounted from the host by docker-compose;
# creating it here provides a sensible default and a stable working directory.
# -----------------------------------------------------------------------------
WORKDIR ${WORKSPACE}

# Keep the container alive for interactive development by default.
CMD ["tail", "-f", "/dev/null"]
