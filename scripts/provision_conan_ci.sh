#!/usr/bin/env bash
#
# Keep this file as the stable user-facing entry point.  The readable
# seven-stage Conan CI access flow lives in Python; this wrapper only selects
# the repository root and forwards the wizard arguments.
#

set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo_root"

exec python3 -m scripts.ci.conan_access_provisioning "$@"
