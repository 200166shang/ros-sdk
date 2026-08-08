#!/usr/bin/env bash
#
# RosBridge Pro container entrypoint.
#
# Sources the ROS 2 environment and, when a colcon workspace overlay has been
# built under /workspace/install, sources that too. Then execs the container
# command so signals and exit codes propagate correctly.
#
set -euo pipefail

# ROS 2 core (Jazzy).
source "/opt/ros/${ROS_DISTRO:-jazzy}/setup.bash"

# Workspace overlay, if the project has been built with colcon.
if [[ -f "${WORKSPACE:-/workspace}/install/setup.bash" ]]; then
  source "${WORKSPACE:-/workspace}/install/setup.bash"
fi

exec "$@"
