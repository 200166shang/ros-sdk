# =============================================================================
# RosBridge Pro — development image
#
#   Single-stage build on ros:jazzy-ros-core to keep image size manageable
#   and avoid keeping intermediate stage images that exhaust Colima disk space.
#
#   rosdep packages are installed together so the layer stays cache-reusable
#   across source-only rebuilds.
# =============================================================================

ARG ROS_DISTRO=jazzy

FROM ros:${ROS_DISTRO}-ros-core

ARG DEBIAN_FRONTEND=noninteractive
ARG ROS_DISTRO

ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8
ENV ROS_DISTRO=${ROS_DISTRO}
ENV RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
ENV TURTLEBOT3_MODEL=burger
ENV WORKSPACE=/workspace

# ---------------------------------------------------------------------------
# System + ROS2 + Gazebo + TurtleBot3 — single RUN to keep one layer
#
# rosdep init/update runs here so future source changes don't invalidate
# the apt cache layer above.
# ---------------------------------------------------------------------------
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        clang-format \
        clang-tidy \
        cmake \
        git \
        python3-colcon-common-extensions \
        python3-pip \
        python3-rosdep \
        ros-${ROS_DISTRO}-rmw-cyclonedds-cpp \
        ros-${ROS_DISTRO}-ros-gz \
        ros-${ROS_DISTRO}-turtlebot3 \
        ros-${ROS_DISTRO}-turtlebot3-bringup \
        ros-${ROS_DISTRO}-turtlebot3-description \
        ros-${ROS_DISTRO}-turtlebot3-gazebo \
        ros-${ROS_DISTRO}-turtlebot3-simulations \
        ros-${ROS_DISTRO}-turtlebot3-teleop \
        xvfb \
    && rm -rf /var/lib/apt/lists/* \
    && rosdep init 2>/dev/null || true \
    && rosdep update

# ---------------------------------------------------------------------------
# Conan package manager
# ---------------------------------------------------------------------------
RUN python3 -m pip install --no-cache-dir --break-system-packages conan \
    && conan profile detect --force

# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
# Source ROS2 environment for both interactive shells (docker run -it) and
# non-interactive exec (docker exec ... bash -c).
#
# Ubuntu's default .bashrc returns early when PS1 is unset (non-interactive).
# We insert the ROS2 source before that guard so bash -c also gets it.
RUN sed -i '1i source /opt/ros/jazzy/setup.bash\n[ -f /workspace/install/setup.bash ] && source /workspace/install/setup.bash || true' /root/.bashrc
ENV BASH_ENV=/root/.bashrc

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]

WORKDIR ${WORKSPACE}
CMD ["tail", "-f", "/dev/null"]
