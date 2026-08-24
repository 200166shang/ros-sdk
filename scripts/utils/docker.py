"""Thin wrapper around docker-compose / docker compose."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

from scripts.utils.config import COMPOSE_FILE, COMPOSE_PROJECT_NAME


class DockerManager:
    """Manage the RosBridge development containers."""

    def __init__(self) -> None:
        self._compose_bin = self._detect_compose()
        self._project_name = os.environ.get("COMPOSE_PROJECT_NAME", COMPOSE_PROJECT_NAME)

    # -- compose detection ---------------------------------------------------

    @staticmethod
    def _detect_compose() -> list[str]:
        """Return the compose command available on this host."""
        if shutil.which("docker-compose"):
            return ["docker-compose"]
        try:
            subprocess.run(
                ["docker", "compose", "version"],
                capture_output=True,
                check=True,
            )
            return ["docker", "compose"]
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass
        print(
            "error: neither 'docker compose' nor 'docker-compose' found",
            file=sys.stderr,
        )
        sys.exit(1)

    # -- public API ----------------------------------------------------------

    def up(self) -> None:
        """Start all services in the background."""
        self._run("up", "--detach")

    def down(self) -> None:
        """Stop and remove containers."""
        self._run("down")

    def build(self) -> None:
        """Build (or rebuild) the ros2 image."""
        self._run("build")

    def exec(self, *cmd: str) -> None:
        """Run a command inside the 'ros2' service container."""
        # Prefer -it when stdout is a terminal, otherwise plain exec.
        args: list[str] = []
        if sys.stdout.isatty():
            args.append("-it")
        self._run("exec", *args, "ros2", *cmd)

    def exec_detached(self, *cmd: str) -> None:
        """Run a command detached inside the 'ros2' service container."""
        self._run("exec", "-d", "ros2", *cmd)

    def ps(self) -> None:
        """List running services."""
        self._run("ps")

    # -- helpers -------------------------------------------------------------

    def _run(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        cmd = [
            *self._compose_bin,
            "-f",
            str(COMPOSE_FILE),
            "-p",
            self._project_name,
            *args,
        ]
        try:
            return subprocess.run(cmd, check=check)
        except subprocess.CalledProcessError as exc:
            if check:
                print(f"error: docker command failed (exit {exc.returncode})",
                      file=sys.stderr)
                sys.exit(exc.returncode)
            return exc  # type: ignore[return-value]
