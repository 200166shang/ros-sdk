"""Safely apply the provisioned read-only identity to Conan Server config."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path


_SECTION_HEADER = re.compile(r"(?m)^\[([^]\n]+)\]\s*$")


def _section_span(config: str, name: str) -> tuple[int, int, int]:
    matches = list(_SECTION_HEADER.finditer(config))
    for index, match in enumerate(matches):
        if match.group(1) == name:
            end = matches[index + 1].start() if index + 1 < len(matches) else len(config)
            return match.start(), match.end() + 1, end
    raise ValueError(f"missing [{name}] section")


def _section_body(config: str, name: str) -> str:
    _, content_start, end = _section_span(config, name)
    return config[content_start:end].rstrip("\n")


def _replace_section(config: str, name: str, body: str) -> str:
    start, _, end = _section_span(config, name)
    replacement = f"[{name}]\n{body.rstrip()}\n\n"
    return config[:start] + replacement + config[end:]


def update_server_config(
    current: str,
    *,
    username: str,
    password: str | None,
) -> str:
    """Return config with the dedicated identity and exact-package authorizer."""
    if not re.fullmatch(r"[A-Za-z0-9_.@+-]+", username):
        raise ValueError("invalid Conan username")
    if password is not None and (
        not password or any(character in password for character in "\r\n:")
    ):
        raise ValueError("invalid Conan password")

    server = _section_body(current, "server")
    custom_authorizer = re.compile(r"^\s*custom_authorizer\s*:")
    configured_authorizers = [
        line.split(":", maxsplit=1)[1].strip()
        for line in server.splitlines()
        if custom_authorizer.match(line)
    ]
    if any(
        value and value != "rosbridge_exact_reader" for value in configured_authorizers
    ):
        raise ValueError("server already uses a different custom authorizer")
    server_lines = [
        line for line in server.splitlines() if not custom_authorizer.match(line)
    ]
    server_lines.append("custom_authorizer: rosbridge_exact_reader")
    updated = _replace_section(current, "server", "\n".join(server_lines))

    users = _section_body(updated, "users")
    user_line = re.compile(rf"^\s*{re.escape(username)}\s*:")
    user_lines = users.splitlines()
    existing_user = any(user_line.match(line) for line in user_lines)
    if password is None:
        if not existing_user:
            raise ValueError("dedicated Conan user does not exist for credential reuse")
    else:
        user_lines = [line for line in user_lines if not user_line.match(line)]
        user_lines.append(f"{username}: {password}")
    return _replace_section(updated, "users", "\n".join(user_lines)).rstrip() + "\n"


def apply_config(
    config_path: Path,
    username: str,
    password_path: Path,
    plugin_path: Path,
    policy_path: Path,
) -> Path:
    """Back up and atomically update a Conan Server configuration file."""
    current = config_path.read_text(encoding="utf-8")
    password_value = password_path.read_text(encoding="utf-8").strip()
    password = password_value or None
    updated = update_server_config(
        current,
        username=username,
        password=password,
    )

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = config_path.with_name(f"{config_path.name}.bak.{timestamp}")
    shutil.copy2(config_path, backup)
    current_stat = config_path.stat()
    file_mode = current_stat.st_mode & 0o777

    plugin_directory = config_path.parent / "plugins" / "authorizer"
    plugin_directory.mkdir(mode=0o755, parents=True, exist_ok=True)
    for source, destination_name in (
        (plugin_path, "rosbridge_exact_reader.py"),
        (policy_path, "rosbridge_exact_reader_policy.json"),
    ):
        destination = plugin_directory / destination_name
        shutil.copyfile(source, destination)
        destination.chmod(0o644)
        os.chown(destination, current_stat.st_uid, current_stat.st_gid)

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{config_path.name}.", dir=str(config_path.parent)
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(updated)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary_name, file_mode)
        os.chown(temporary_name, current_stat.st_uid, current_stat.st_gid)
        os.replace(temporary_name, config_path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)

    return backup


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply restricted Conan Server identity")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument("--password-file", type=Path, required=True)
    parser.add_argument("--plugin", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    args = parser.parse_args()
    backup = apply_config(
        args.config,
        args.username,
        args.password_file,
        args.plugin,
        args.policy,
    )
    print(f"Conan Server config updated; backup: {backup}")


if __name__ == "__main__":
    main()
