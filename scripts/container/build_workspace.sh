#!/usr/bin/env bash

set -euo pipefail

cd /workspace

if [[ "${1:-}" == "--clean" ]]; then
  rm -rf build install log
fi

remote_name="${CONAN_REMOTE_NAME:-rosbridge}"
conan remote disable "$remote_name" >/dev/null 2>&1 || true

if [[ -n "${CONAN_REMOTE_URL:-}" ]]; then
  if conan remote add "$remote_name" "$CONAN_REMOTE_URL" \
    --index 0 --force >/dev/null 2>&1; then
    if [[ -n "${CONAN_LOGIN_USERNAME:-}" && -n "${CONAN_PASSWORD:-}" ]] \
      && conan remote login "$remote_name" "$CONAN_LOGIN_USERNAME" \
        -p "$CONAN_PASSWORD" >/dev/null 2>&1; then
      conan remote enable "$remote_name" >/dev/null 2>&1 || true
      echo "Conan remote enabled: $remote_name"
    else
      conan remote disable "$remote_name" >/dev/null 2>&1 || true
      echo "Conan remote unavailable or unauthenticated; using fallback"
    fi
  else
    echo "Conan remote configuration failed; using fallback"
  fi
else
  echo "Conan remote not configured; using default remotes"
fi

echo "Conan version: $(conan --version)"
echo "Conan host settings: arch=armv8 compiler=gcc compiler.version=13 compiler.cppstd=17 build_type=Release"

SECONDS=0
conan install . \
  --lockfile=conan.lock \
  --output-folder=build \
  --build=missing \
  -s build_type=Release \
  -s compiler.cppstd=17
echo "Conan install elapsed: ${SECONDS}s"

source build/conanbuild.sh
colcon build --base-paths src --symlink-install \
  --cmake-args \
  -DCMAKE_TOOLCHAIN_FILE=/workspace/build/conan_toolchain.cmake \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_EXPORT_COMPILE_COMMANDS=ON
