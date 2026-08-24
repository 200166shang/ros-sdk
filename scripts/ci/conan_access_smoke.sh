#!/usr/bin/env bash

set -euo pipefail

required=(
  CONAN_SSH_PRIVATE_KEY
  CONAN_SSH_KNOWN_HOSTS
  CONAN_SSH_HOST
  CONAN_SSH_PORT
  CONAN_SSH_USER
  CONAN_SSH_TARGET_HOST
  CONAN_SSH_TARGET_PORT
  CONAN_LOGIN_USERNAME
  CONAN_PASSWORD
  CI_IMAGE
)
for name in "${required[@]}"; do
  [[ -n ${!name:-} ]] || { echo "error: required secret $name is not configured" >&2; exit 2; }
done

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
netrc=$work_dir/netrc
token_config=$work_dir/token.curlrc
printf '%s\n' "$CONAN_SSH_PRIVATE_KEY" > "$private_key"
printf '%s\n' "$CONAN_SSH_KNOWN_HOSTS" > "$known_hosts"
printf 'machine 127.0.0.1 login %s password %s\n' \
  "$CONAN_LOGIN_USERNAME" "$CONAN_PASSWORD" > "$netrc"
chmod 0600 "$private_key" "$known_hosts" "$netrc"

local_port=${CONAN_SMOKE_LOCAL_PORT:-19300}
ssh_options=(
  -N
  -o BatchMode=yes
  -o ClearAllForwardings=yes
  -o ExitOnForwardFailure=yes
  -o IdentitiesOnly=yes
  -o LogLevel=ERROR
  -o StrictHostKeyChecking=yes
  -o "UserKnownHostsFile=$known_hosts"
  -i "$private_key"
  -p "$CONAN_SSH_PORT"
  -L "127.0.0.1:$local_port:$CONAN_SSH_TARGET_HOST:$CONAN_SSH_TARGET_PORT"
  "$CONAN_SSH_USER@$CONAN_SSH_HOST"
)
ssh "${ssh_options[@]}" &
ssh_pid=$!

for _ in 1 2 3 4 5; do
  kill -0 "$ssh_pid" >/dev/null 2>&1 || {
    wait "$ssh_pid" || true
    echo "error: restricted SSH tunnel failed" >&2
    exit 1
  }
  if curl --fail --silent --show-error --max-time 5 \
      "http://127.0.0.1:$local_port/v1/ping" >/dev/null; then
    break
  fi
  sleep 1
done
curl --fail --silent --show-error --max-time 5 \
  "http://127.0.0.1:$local_port/v1/ping" >/dev/null
conan_token=$(curl --fail --silent --show-error --max-time 5 \
  --netrc-file "$netrc" \
  "http://127.0.0.1:$local_port/v2/users/authenticate")

# DELETE targets a cryptographically unique, nonexistent recipe. A correctly restricted
# identity is rejected by the authorizer before the storage layer can run; a writable
# identity reaches the harmless nonexistent target and returns something other than 403.
probe_name="rosbridge-ci-write-probe-$(openssl rand -hex 16)"
printf 'header = "Authorization: Bearer %s"\n' "$conan_token" > "$token_config"
chmod 0600 "$token_config"
write_status=$(curl --silent --show-error --max-time 5 \
  --config "$token_config" \
  --output /dev/null --write-out '%{http_code}' \
  --request DELETE \
  "http://127.0.0.1:$local_port/v2/conans/$probe_name/0/_/_")
[[ $write_status == 403 ]] || {
  echo "error: Conan credential is not proven read-only (write probe returned $write_status)" >&2
  exit 1
}
rm -f "$token_config"
unset conan_token

docker pull "$CI_IMAGE" >/dev/null
docker run --rm --network host \
  --env CONAN_LOGIN_USERNAME \
  --env CONAN_PASSWORD \
  --env "CONAN_REMOTE_URL=http://127.0.0.1:$local_port" \
  --mount "type=bind,src=$PWD,dst=/workspace,readonly" \
  --workdir /workspace \
  "$CI_IMAGE" \
  bash -euo pipefail -c '
    smoke_home=$(mktemp -d)
    trap '\''rm -rf "$smoke_home"'\'' EXIT
    export CONAN_HOME="$smoke_home/conan-home"
    conan profile detect --force >/dev/null
    conan remote add rosbridge "$CONAN_REMOTE_URL" --force >/dev/null
    conan remote auth rosbridge --force --strict >/dev/null
    conan install . \
      --lockfile=conan.lock \
      --output-folder="$smoke_home/output" \
      --remote=rosbridge \
      --build=never \
      --conf "tools.cmake.cmaketoolchain:user_presets=" \
      -s:h arch=armv8 \
      -s:h build_type=Release \
      -s:h compiler.cppstd=17 \
      -s:b arch=armv8 \
      -s:b build_type=Release \
      -s:b compiler.cppstd=17 \
      >/dev/null
  '

echo "Conan access smoke passed: host, tunnel, auth, write denial, and exact ARM64 read"
