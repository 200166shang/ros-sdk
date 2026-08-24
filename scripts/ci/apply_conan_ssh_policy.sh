#!/usr/bin/env bash

set -euo pipefail

usage() {
  echo "usage: $0 install <ssh-user> <key-id> <bundle-dir> | remove <ssh-user> <key-id>" >&2
  exit 2
}

[[ $EUID -eq 0 ]] || { echo "error: run as root" >&2; exit 1; }
[[ $# -ge 3 ]] || usage

action=$1
ssh_user=$2
key_id=$3
[[ $ssh_user =~ ^[a-z_][a-z0-9_-]*$ ]] || { echo "error: invalid SSH user" >&2; exit 1; }
[[ $key_id =~ ^[A-Za-z0-9][A-Za-z0-9._:-]*$ ]] || { echo "error: invalid key ID" >&2; exit 1; }

reload_sshd() {
  if command -v systemctl >/dev/null 2>&1; then
    systemctl reload sshd 2>/dev/null || systemctl reload ssh
  else
    service sshd reload 2>/dev/null || service ssh reload
  fi
}

if [[ $action == install ]]; then
  [[ $# -eq 4 ]] || usage
  bundle_dir=$4
  [[ -f $bundle_dir/authorized_key && -f $bundle_dir/sshd_config ]] || {
    echo "error: incomplete SSH policy bundle" >&2
    exit 1
  }

  if ! id "$ssh_user" >/dev/null 2>&1; then
    nologin_shell=$(command -v nologin || echo /usr/sbin/nologin)
    useradd --system --create-home --shell "$nologin_shell" "$ssh_user"
  fi
  nologin_shell=$(command -v nologin || echo /usr/sbin/nologin)
  usermod --shell "$nologin_shell" "$ssh_user"
  user_home=$(getent passwd "$ssh_user" | cut -d: -f6)
  user_group=$(id -gn "$ssh_user")
  install -d -m 0700 -o "$ssh_user" -g "$user_group" "$user_home/.ssh"
  touch "$user_home/.ssh/authorized_keys"
  chown "$ssh_user:$user_group" "$user_home/.ssh/authorized_keys"
  chmod 0600 "$user_home/.ssh/authorized_keys"
  if ! grep -Fq " $key_id" "$user_home/.ssh/authorized_keys"; then
    cat "$bundle_dir/authorized_key" >> "$user_home/.ssh/authorized_keys"
  fi

  install -d -o root -g root -m 0755 /etc/ssh/sshd_config.d
  sshd_policy=/etc/ssh/sshd_config.d/60-rosbridge-conan-ci.conf
  policy_backup=$(mktemp)
  had_existing_policy=false
  if [[ -f $sshd_policy ]]; then
    cp "$sshd_policy" "$policy_backup"
    had_existing_policy=true
  fi
  trap 'rm -f "$policy_backup"' EXIT
  install -o root -g root -m 0644 "$bundle_dir/sshd_config" \
    "$sshd_policy"
  expected_permit_open=$(awk '$1 == "PermitOpen" { print "permitopen " $2 }' \
    "$bundle_dir/sshd_config")
  validate_effective_policy() {
    grep -Fqx "allowtcpforwarding local" <<<"$effective" &&
      grep -Fqx "allowstreamlocalforwarding no" <<<"$effective" &&
      grep -Fqx "$expected_permit_open" <<<"$effective" &&
      grep -Fqx "permitlisten none" <<<"$effective" &&
      grep -Fqx "permittty no" <<<"$effective" &&
      grep -Fqx "allowagentforwarding no" <<<"$effective" &&
      grep -Fqx "x11forwarding no" <<<"$effective" &&
      grep -Fqx "passwordauthentication no" <<<"$effective" &&
      grep -Fqx "kbdinteractiveauthentication no" <<<"$effective" &&
      grep -Fqx "gatewayports no" <<<"$effective"
  }
  if ! sshd -t ||
    ! effective=$(sshd -T -C "user=$ssh_user,host=localhost,addr=127.0.0.1") ||
    ! validate_effective_policy; then
    if $had_existing_policy; then
      install -o root -g root -m 0644 "$policy_backup" "$sshd_policy"
    else
      rm -f "$sshd_policy"
    fi
    echo "error: refusing to reload sshd because the restricted policy is ineffective" >&2
    exit 1
  fi
  reload_sshd
  echo "restricted SSH key installed: $key_id"
elif [[ $action == remove ]]; then
  [[ $# -eq 3 ]] || usage
  user_home=$(getent passwd "$ssh_user" | cut -d: -f6)
  authorized_keys=$user_home/.ssh/authorized_keys
  [[ -f $authorized_keys ]] || { echo "error: authorized_keys not found" >&2; exit 1; }
  awk -v key_id="$key_id" '$NF == key_id { found = 1 } END { exit !found }' \
    "$authorized_keys" || { echo "error: key ID not found: $key_id" >&2; exit 1; }
  temporary=$(mktemp)
  trap 'rm -f "$temporary"' EXIT
  awk -v key_id="$key_id" '$NF != key_id' "$authorized_keys" > "$temporary"
  install -o "$ssh_user" -g "$(id -gn "$ssh_user")" -m 0600 \
    "$temporary" "$authorized_keys"
  echo "restricted SSH key removed: $key_id"
else
  usage
fi
