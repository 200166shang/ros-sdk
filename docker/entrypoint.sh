#!/usr/bin/env bash
#
# RosBridge Pro container entrypoint.
#
# Sources the ROS 2 environment (and the TurtleBot3 workspace if installed,
# and the project workspace overlay if built), then execs the container command
# so signals and exit codes propagate correctly.
#
set -eo pipefail

# ROS 2 core (Jazzy) — this already sources TurtleBot3 if it was built.
source "/opt/ros/${ROS_DISTRO:-jazzy}/setup.bash"

# Project workspace overlay (built by the developer with colcon).
if [[ -f "${WORKSPACE:-/workspace}/install/setup.bash" ]]; then
  source "${WORKSPACE:-/workspace}/install/setup.bash"
fi

exec "$@"
