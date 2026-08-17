#!/usr/bin/env bash

set -euo pipefail

: "${ROSBRIDGE_IMAGE:?ROSBRIDGE_IMAGE must be set}"

runner_arch="$(uname -m)"
container_arch="$(docker exec ros2 uname -m)"
image_arch="$(docker image inspect "$ROSBRIDGE_IMAGE" --format '{{.Architecture}}')"

test "$runner_arch" = "aarch64"
test "$container_arch" = "aarch64"
test "$image_arch" = "arm64"

docker exec ros2 bash -lc \
  'conan profile show -pr:h default | grep -Fx "arch=armv8"'

echo "ARM64 build environment verified"
