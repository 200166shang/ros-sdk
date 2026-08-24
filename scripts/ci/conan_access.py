"""Security policy helpers for the Conan CI provisioning wizard."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
from pathlib import Path

from scripts.ci.conan_exact_reader_authorizer import ExactPackagePolicy


_HOST_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_KEY_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_OS_USERNAME_PATTERN = re.compile(r"^[a-z_][a-z0-9_-]*[$]?$")
_ARM64_PROFILE = {
    "os": "Linux",
    "arch": "armv8",
    "compiler": "gcc",
    "compiler.version": "13",
    "compiler.libcxx": "libstdc++11",
    "compiler.cppstd": "17",
    "build_type": "Release",
}


def _validate_endpoint(host: str, port: int) -> None:
    if not _HOST_PATTERN.fullmatch(host):
        raise ValueError("destination host must be a literal host name or address")
    if not 1 <= port <= 65535:
        raise ValueError("destination port must be between 1 and 65535")


def authorized_key_entry(
    public_key: str,
    destination_host: str,
    destination_port: int,
    key_id: str,
) -> str:
    """Build the restricted OpenSSH authorized_keys entry for CI tunneling."""
    _validate_endpoint(destination_host, destination_port)
    key_parts = public_key.strip().split()
    if len(key_parts) < 2 or key_parts[0] != "ssh-ed25519":
        raise ValueError("public key must be an Ed25519 OpenSSH public key")
    if not re.fullmatch(r"[A-Za-z0-9+/=]+", key_parts[1]):
        raise ValueError("public key must contain valid OpenSSH key material")
    if not _KEY_ID_PATTERN.fullmatch(key_id):
        raise ValueError("key ID contains unsupported characters")
    key_material = " ".join(key_parts[:2])
    return (
        f'restrict,port-forwarding,permitopen="{destination_host}:{destination_port}" '
        f"{key_material} {key_id}"
    )


def sshd_match_block(username: str, destination_host: str, destination_port: int) -> str:
    """Build the dedicated sshd Match block used by the tunnel account."""
    if not _OS_USERNAME_PATTERN.fullmatch(username):
        raise ValueError("SSH username contains unsupported characters")
    _validate_endpoint(destination_host, destination_port)
    return (
        f"Match User {username}\n"
        "  AuthenticationMethods publickey\n"
        "  PasswordAuthentication no\n"
        "  KbdInteractiveAuthentication no\n"
        "  PubkeyAuthentication yes\n"
        "  PermitTTY no\n"
        "  X11Forwarding no\n"
        "  AllowAgentForwarding no\n"
        "  AllowTcpForwarding local\n"
        "  AllowStreamLocalForwarding no\n"
        f"  PermitOpen {destination_host}:{destination_port}\n"
        "  PermitListen none\n"
        "  GatewayPorts no\n"
        "  PermitUserRC no\n"
    )


def load_exact_package_policy(policy_path: Path, lockfile: Path) -> dict[str, object]:
    """Load and validate an exact ARM64 package policy against the lockfile."""
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    lock = json.loads(lockfile.read_text(encoding="utf-8"))
    locked_recipes = {
        reference.split("%", maxsplit=1)[0]
        for section in (
            "requires",
            "build_requires",
            "python_requires",
            "config_requires",
        )
        for reference in lock.get(section, ())
    }
    if policy.get("schema_version") != 1:
        raise ValueError("unsupported exact package policy schema")
    if policy.get("profile") != _ARM64_PROFILE:
        raise ValueError("exact package policy must match the locked ARM64 CI profile")
    policy_recipes = set(policy.get("recipes", ()))
    if policy_recipes != locked_recipes:
        raise ValueError("exact package policy recipes do not match conan.lock")
    packages = policy.get("packages", ())
    if not packages:
        raise ValueError("exact package policy must contain package IDs")
    for package in packages:
        recipe = str(package).split(":", maxsplit=1)[0]
        if recipe not in policy_recipes:
            raise ValueError(f"package is not covered by locked recipes: {package}")
    ExactPackagePolicy(policy)
    return policy


def write_text_securely(path: Path, content: str) -> None:
    """Write a provisioning artifact readable only by its owner."""
    path.write_text(content, encoding="utf-8")
    path.chmod(0o600)


def wait_for_smoke_run(
    workflow: str,
    branch: str,
    nonce: str,
    *,
    attempts: int = 10,
    delay_seconds: float = 2,
) -> int:
    """Return the exact workflow run correlated with a provisioning nonce."""
    expected_title = f"Conan Access Smoke {nonce}"
    for attempt in range(attempts):
        result = subprocess.run(
            [
                "gh",
                "run",
                "list",
                "--workflow",
                workflow,
                "--branch",
                branch,
                "--event",
                "workflow_dispatch",
                "--limit",
                "20",
                "--json",
                "databaseId,displayTitle",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        for run in json.loads(result.stdout):
            if run.get("displayTitle") == expected_title:
                return int(run["databaseId"])
        if attempt + 1 < attempts:
            time.sleep(delay_seconds)
    raise RuntimeError(f"could not find smoke workflow run: {expected_title}")


def render_policy_bundle(args: argparse.Namespace) -> None:
    """Render all server-side policy artifacts for maintainer review."""
    output_directory = Path(args.output_directory)
    output_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    output_directory.chmod(0o700)
    public_key = Path(args.public_key_file).read_text(encoding="utf-8")
    write_text_securely(
        output_directory / "authorized_key",
        authorized_key_entry(
            public_key,
            args.destination_host,
            args.destination_port,
            args.key_id,
        )
        + "\n",
    )
    write_text_securely(
        output_directory / "sshd_config",
        sshd_match_block(
            args.ssh_user,
            args.destination_host,
            args.destination_port,
        ),
    )
    write_text_securely(
        output_directory / "conan_policy.json",
        json.dumps(
            load_exact_package_policy(
                Path(args.package_policy),
                Path(args.lockfile),
            ),
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )


def wait_for_smoke_run_command(args: argparse.Namespace) -> None:
    print(wait_for_smoke_run(args.workflow, args.branch, args.nonce))


def main() -> None:
    parser = argparse.ArgumentParser(description="Render restricted Conan CI access policy")
    subparsers = parser.add_subparsers(dest="command", required=True)
    render = subparsers.add_parser("render", help="render server policy files")
    render.add_argument("--public-key-file", required=True)
    render.add_argument("--destination-host", required=True)
    render.add_argument("--destination-port", type=int, required=True)
    render.add_argument("--key-id", required=True)
    render.add_argument("--ssh-user", required=True)
    render.add_argument("--lockfile", required=True)
    render.add_argument("--package-policy", required=True)
    render.add_argument("--output-directory", required=True)
    render.set_defaults(handler=render_policy_bundle)
    wait = subparsers.add_parser("wait-smoke-run")
    wait.add_argument("--workflow", required=True)
    wait.add_argument("--branch", required=True)
    wait.add_argument("--nonce", required=True)
    wait.set_defaults(handler=wait_for_smoke_run_command)
    args = parser.parse_args()
    args.handler(args)


if __name__ == "__main__":
    main()
