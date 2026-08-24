"""Readable orchestration model for Conan CI access provisioning.

The shell entry point remains intentionally small.  This module owns the
seven-step Conan CI access provisioning flow; the data objects below keep the
inputs and temporary artifacts visible while the flow is running.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


STAGE_NAMES = (
    "Preflight and emergency revocation",
    "Endpoint and identity",
    "Host identity",
    "Restricted server-side SSH policy",
    "Exact read-only Conan identity",
    "Repository Secrets",
    "Trusted smoke and overlap completion",
)

REPOSITORY_SECRET_NAMES = (
    "CONAN_SSH_PRIVATE_KEY",
    "CONAN_SSH_KNOWN_HOSTS",
    "CONAN_SSH_HOST",
    "CONAN_SSH_PORT",
    "CONAN_SSH_USER",
    "CONAN_SSH_TARGET_HOST",
    "CONAN_SSH_TARGET_PORT",
    "CONAN_LOGIN_USERNAME",
    "CONAN_PASSWORD",
)


@dataclass(frozen=True)
class ProvisioningConfig:
    """Values collected from the maintainer before side effects begin."""

    server_admin_target: str
    server_admin_port: int
    emergency_key_id: str
    conan_ssh_host: str
    conan_ssh_port: int
    ssh_user: str
    target_host: str
    target_port: int
    old_key_id: str
    conan_server_config: str
    conan_service: str


@dataclass
class ProvisioningArtifacts:
    """Temporary values produced while the seven stages are running."""

    key_id: str = ""
    private_key: Path | None = None
    known_hosts: Path | None = None
    policy_directory: Path | None = None
    remote_directory: str = ""
    conan_username: str = ""
    conan_password: str = ""
    rotate_after: str = ""
    skipped_actions: list[str] = field(default_factory=list)
    written_secrets: list[str] = field(default_factory=list)


def validate_port(name: str, port: int) -> None:
    """Reject a port outside the range accepted by SSH and Conan Server."""
    if not 1 <= port <= 65535:
        raise ValueError(f"{name} must be between 1 and 65535")


def validate_config(config: ProvisioningConfig) -> None:
    """Validate user input before creating a key or contacting a server."""
    validate_port("server admin port", config.server_admin_port)
    validate_port("public SSH port", config.conan_ssh_port)
    validate_port("Conan target port", config.target_port)
    if not config.server_admin_target:
        raise ValueError("server admin target must not be empty")
    if not config.conan_ssh_host:
        raise ValueError("public SSH host must not be empty")
    if not config.ssh_user:
        raise ValueError("SSH user must not be empty")
    if not config.target_host:
        raise ValueError("Conan target host must not be empty")
    if not config.conan_server_config.startswith("/"):
        raise ValueError("Conan Server config path must be absolute")
    if not config.conan_service:
        raise ValueError("Conan service must not be empty")
