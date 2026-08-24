#!/usr/bin/env bash

set -euo pipefail

required=(
  CI_IMAGE
  CACHE_GENERATION
  SAMPLE_ROLE
  EXPECTED_CACHE_KEY
  CACHE_RESTORE_FAILED
  CACHE_RESTORE_SECONDS
  REPOSITORY_CACHE_BYTES
  CONAN_SSH_PRIVATE_KEY
  CONAN_SSH_KNOWN_HOSTS
  CONAN_SSH_HOST
  CONAN_SSH_PORT
  CONAN_SSH_USER
  CONAN_SSH_TARGET_HOST
  CONAN_SSH_TARGET_PORT
  CONAN_LOGIN_USERNAME
  CONAN_PASSWORD
)
for name in "${required[@]}"; do
  if [[ -z ${!name:-} ]]; then
    echo "error: required environment is not configured: $name" >&2
    exit 2
  fi
done

if [[ ! $CONAN_SSH_HOST =~ ^[A-Za-z0-9][A-Za-z0-9.-]{0,252}$ ]] ||
  [[ ! $CONAN_SSH_USER =~ ^[A-Za-z_][A-Za-z0-9._-]{0,31}$ ]] ||
  [[ ! $CONAN_SSH_TARGET_HOST =~ ^[A-Za-z0-9][A-Za-z0-9.-]{0,252}$ ]] ||
  [[ ! $CONAN_SSH_PORT =~ ^[0-9]{1,5}$ ]] ||
  [[ ! $CONAN_SSH_TARGET_PORT =~ ^[0-9]{1,5}$ ]]; then
  echo "error: restricted SSH endpoint is invalid" >&2
  exit 2
fi
ssh_port=$((10#$CONAN_SSH_PORT))
target_port=$((10#$CONAN_SSH_TARGET_PORT))
if ((ssh_port < 1 || ssh_port > 65535 || target_port < 1 || target_port > 65535)); then
  echo "error: restricted SSH endpoint is invalid" >&2
  exit 2
fi
if [[ $CACHE_RESTORE_FAILED != true && $CACHE_RESTORE_FAILED != false ]]; then
  echo "error: cache restore state is invalid" >&2
  exit 2
fi

umask 077
work_dir=$(mktemp -d)
ssh_pid=""
cleanup() {
  if [[ -n $ssh_pid ]]; then
    kill "$ssh_pid" >/dev/null 2>&1 || true
    wait "$ssh_pid" >/dev/null 2>&1 || true
  fi
  rm -rf "$work_dir"
}
trap cleanup EXIT HUP INT TERM

private_key=$work_dir/id_ed25519
known_hosts=$work_dir/known_hosts
printf '%s\n' "$CONAN_SSH_PRIVATE_KEY" > "$private_key"
printf '%s\n' "$CONAN_SSH_KNOWN_HOSTS" > "$known_hosts"
chmod 0600 "$private_key" "$known_hosts"

local_port=19300
ssh_options=(
  -F /dev/null
  -N
  -o BatchMode=yes
  -o CanonicalizeHostname=no
  -o ClearAllForwardings=yes
  -o ExitOnForwardFailure=yes
  -o GlobalKnownHostsFile=/dev/null
  -o IdentitiesOnly=yes
  -o LogLevel=ERROR
  -o ProxyCommand=none
  -o ProxyJump=none
  -o StrictHostKeyChecking=yes
  -o "UserKnownHostsFile=$known_hosts"
  -i "$private_key"
  -p "$ssh_port"
  -L "127.0.0.1:$local_port:$CONAN_SSH_TARGET_HOST:$target_port"
  "$CONAN_SSH_USER@$CONAN_SSH_HOST"
)
ssh "${ssh_options[@]}" &
ssh_pid=$!

tunnel_ready=false
for _ in 1 2 3 4 5; do
  if ! kill -0 "$ssh_pid" >/dev/null 2>&1; then
    break
  fi
  if curl --fail --silent --show-error --max-time 5 \
    "http://127.0.0.1:$local_port/v1/ping" >/dev/null; then
    tunnel_ready=true
    break
  fi
  sleep 1
done
if [[ $tunnel_ready != true ]]; then
  echo "error: restricted Conan tunnel failed" >&2
  exit 1
fi

mkdir -p .cache/conan-download .cache/conan-canary build
docker run --rm --network host \
  --tmpfs /tmp:rw,nosuid,nodev,size=2g \
  --env CACHE_GENERATION \
  --env SAMPLE_ROLE \
  --env EXPECTED_CACHE_KEY \
  --env MATCHED_CACHE_KEY \
  --env CACHE_RESTORE_FAILED \
  --env CACHE_RESTORE_SECONDS \
  --env REPOSITORY_CACHE_BYTES \
  --env CONAN_LOGIN_USERNAME \
  --env CONAN_PASSWORD \
  --env "CONAN_REMOTE_URL=http://127.0.0.1:$local_port" \
  --volume "$PWD:/workspace" \
  --workdir /workspace \
  "$CI_IMAGE" \
  bash -euo pipefail -c '
    export CONAN_HOME=/tmp/conan-home
    restore_arguments=()
    if [[ "$CACHE_RESTORE_FAILED" == true ]]; then
      restore_arguments+=(--restore-failed)
    fi
    python3 -m scripts.ci cache-run \
      --generation "$CACHE_GENERATION" \
      --sample-role "$SAMPLE_ROLE" \
      --expected-key "$EXPECTED_CACHE_KEY" \
      --matched-key "${MATCHED_CACHE_KEY:-}" \
      "${restore_arguments[@]}" \
      --restore-seconds "$CACHE_RESTORE_SECONDS" \
      --repository-cache-bytes "$REPOSITORY_CACHE_BYTES" \
      --remote rosbridge \
      --remote-url "$CONAN_REMOTE_URL" \
      --cache-dir /workspace/.cache/conan-download \
      --graph-output /workspace/.cache/conan-canary/graph.json \
      --output-folder /workspace/build \
      --result-output /workspace/.cache/conan-canary/result.json
  '

echo "Conan cache canary completed through the restricted Server tunnel"
