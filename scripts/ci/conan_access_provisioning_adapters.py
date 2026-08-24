"""External-system adapters for the Conan CI access provisioning flow.

The workflow module only talks in terms of named actions.  This file contains
the small amount of subprocess, SSH and GitHub API code needed to perform them.
"""

from __future__ import annotations

import subprocess
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import posixpath
from typing import Iterator


class AdapterError(RuntimeError):
    """An external command or API operation failed."""


@dataclass(frozen=True)
class RemoteResult:
    """The part of a Fabric result used by the workflow."""

    returncode: int
    stdout: str = ""
    stderr: str = ""


class LocalCommandAdapter:
    """Run local commands and check the maintainer's prerequisites."""

    def run(self, args: list[str], **kwargs: object):
        return subprocess.run(args, **kwargs)

    def require_commands(self) -> None:
        for command in ("gh", "ssh-keygen", "ssh-keyscan"):
            if _which(command) is None:
                raise AdapterError(f"missing command: {command}")

    def scan_host(self, host: str, port: int) -> str:
        result = self.run(
            ["ssh-keyscan", "-p", str(port), host],
            check=True,
            capture_output=True,
            text=True,
        )
        if not result.stdout.strip():
            raise AdapterError("no SSH host keys received")
        return result.stdout

    def show_fingerprints(self, known_hosts: Path) -> str:
        result = self.run(
            ["ssh-keygen", "-lf", str(known_hosts)],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    def create_identity(self, private_key: Path, key_id: str) -> None:
        self.run(
            [
                "ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C",
                key_id, "-f", str(private_key),
            ],
            check=True,
        )


class FabricSshAdapter:
    """Perform remote administration through Fabric and Paramiko."""

    def __init__(self, commands: LocalCommandAdapter) -> None:
        self.commands = commands

    def _connection(self, target: str, port: int, known_hosts: Path | None = None):
        try:
            from fabric import Connection, Config
            from paramiko.client import RejectPolicy
        except ImportError as error:  # pragma: no cover - dependency check
            raise AdapterError("install scripts/requirements.txt before using Fabric") from error

        user, host = _split_target(target)
        config = Config(overrides={"load_ssh_configs": False})
        connection = Connection(
            host=host,
            user=user,
            port=port,
            config=config,
            connect_kwargs={"allow_agent": False},
        )
        # Fabric defaults to AutoAddPolicy; provisioning must reject an
        # unrecognised host instead of silently trusting it.
        connection.client.load_system_host_keys()
        connection.client.set_missing_host_key_policy(RejectPolicy())
        if known_hosts is not None:
            connection.client.load_host_keys(str(known_hosts))
        return connection

    def run_remote(
        self,
        target: str,
        port: int,
        command: str,
        *,
        check: bool = True,
    ) -> RemoteResult:
        connection = self._connection(target, port)
        try:
            result = connection.run(command, hide=True, warn=not check)
            return RemoteResult(result.exited, result.stdout, result.stderr)
        except Exception as error:
            raise AdapterError(f"remote command failed: {command}") from error
        finally:
            connection.close()

    def copy_to(self, paths: list[Path], target: str, port: int) -> None:
        remote_target, remote_path = _split_destination(target)
        connection = self._connection(remote_target, port)
        try:
            for path in paths:
                destination = remote_path
                if len(paths) > 1 or remote_path.endswith("/"):
                    destination = posixpath.join(remote_path, path.name)
                connection.put(str(path), remote=destination)
        except Exception as error:
            raise AdapterError(f"could not copy files to {target}") from error
        finally:
            connection.close()

    def install_ssh_policy(
        self,
        target: str,
        port: int,
        remote_directory: str,
        ssh_user: str,
        key_id: str,
    ) -> None:
        self.run_remote(
            target,
            port,
            "sudo bash {script} install {user} {key} {remote}".format(
                script=_quote(f"{remote_directory}/apply_conan_ssh_policy.sh"),
                user=_quote(ssh_user),
                key=_quote(key_id),
                remote=_quote(remote_directory),
            ),
        )

    def create_remote_directory(self, target: str, port: int, remote_directory: str) -> None:
        self.run_remote(target, port, f"mkdir -m 700 {_quote(remote_directory)}")

    def revoke_key(
        self,
        target: str,
        port: int,
        script: Path,
        ssh_user: str,
        key_id: str,
    ) -> None:
        remote_script = "/tmp/apply-conan-ssh-policy.sh"
        self.copy_to([script], f"{target}:{remote_script}", port)
        self.run_remote(
            target,
            port,
            "sudo bash {script} remove {user} {key}; rm -f {script}".format(
                script=_quote(remote_script),
                user=_quote(ssh_user),
                key=_quote(key_id),
            ),
        )

    def install_conan_identity(
        self,
        target: str,
        port: int,
        remote_directory: str,
        config_path: str,
        username: str,
    ) -> None:
        command = (
            "sudo python3 {updater} --config {config} --username {username} "
            "--password-file {password} --plugin {plugin} --policy {policy}"
        ).format(
            updater=_quote(f"{remote_directory}/apply_conan_server_config.py"),
            config=_quote(config_path),
            username=_quote(username),
            password=_quote(f"{remote_directory}/conan_password"),
            plugin=_quote(f"{remote_directory}/conan_exact_reader_authorizer.py"),
            policy=_quote(f"{remote_directory}/conan_policy.json"),
        )
        self.run_remote(target, port, command)

    def restart_service(self, target: str, port: int, service: str) -> RemoteResult:
        return self.run_remote(target, port, f"sudo systemctl restart {_quote(service)}", check=False)

    def remove_remote_directory(self, target: str, port: int, remote_directory: str) -> None:
        self.run_remote(target, port, f"rm -rf {_quote(remote_directory)}", check=False)

    @contextmanager
    def forward_local(
        self,
        target: str,
        port: int,
        local_port: int,
        remote_host: str,
        remote_port: int,
    ) -> Iterator[None]:
        """Expose a remote Conan endpoint through Fabric's local tunnel."""
        connection = self._connection(target, port)
        try:
            with connection.forward_local(
                local_port,
                remote_port,
                remote_host=remote_host,
            ):
                yield
        finally:
            connection.close()


class GitHubAdapter:
    """Use PyGithub for repository secrets, variables and workflow runs."""

    def __init__(self, commands: LocalCommandAdapter) -> None:
        self.commands = commands
        self._client = None
        self._repo = None

    def authenticate(self) -> bool:
        result = self.commands.run(
            ["gh", "auth", "status"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if result.returncode != 0:
            return False
        try:
            token_result = self.commands.run(
                ["gh", "auth", "token"],
                check=True,
                capture_output=True,
                text=True,
            )
            from github import Auth, Github

            token = token_result.stdout.strip()
            if not token:
                return False
            self._client = Github(auth=Auth.Token(token))
            repository_result = self.commands.run(
                ["gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"],
                check=True,
                capture_output=True,
                text=True,
            )
            self._repo = self._client.get_repo(repository_result.stdout.strip())
            return True
        except Exception as error:
            raise AdapterError("could not initialize the PyGithub client") from error

    @property
    def repo(self):
        if self._repo is None:
            raise AdapterError("GitHub adapter is not authenticated")
        return self._repo

    def set_secret(self, name: str, value: str) -> None:
        self.repo.create_secret(name, value)

    def set_variable(self, name: str, value: str) -> None:
        try:
            self.repo.get_variable(name).edit(value=value)
        except Exception as error:
            if getattr(error, "status", None) != 404:
                raise AdapterError(f"could not update GitHub variable {name}") from error
            self.repo.create_variable(name, value)

    def default_branch(self) -> str:
        return self.repo.default_branch

    def dispatch_smoke(self, workflow: str, branch: str, nonce: str) -> None:
        self.repo.get_workflow(workflow).create_dispatch(branch, {"nonce": nonce})

    def wait_for_smoke_run(
        self,
        workflow: str,
        branch: str,
        nonce: str,
        *,
        attempts: int = 10,
        delay_seconds: float = 2,
    ) -> int:
        expected_title = f"Conan Access Smoke {nonce}"
        workflow_object = self.repo.get_workflow(workflow)
        for attempt in range(attempts):
            for run in workflow_object.get_runs(branch=branch, event="workflow_dispatch"):
                if getattr(run, "display_title", "") == expected_title:
                    return run.id
            if attempt + 1 < attempts:
                time.sleep(delay_seconds)
        raise AdapterError(f"could not find smoke workflow run: {expected_title}")

    def watch_run(self, run_id: int, *, attempts: int = 150, delay_seconds: float = 2) -> None:
        for attempt in range(attempts):
            run = self.repo.get_workflow_run(run_id)
            if run.status == "completed":
                if run.conclusion != "success":
                    raise AdapterError(f"smoke workflow failed: {run.conclusion}")
                return
            if attempt + 1 < attempts:
                time.sleep(delay_seconds)
        raise AdapterError(f"smoke workflow did not finish: {run_id}")


def _which(command: str) -> str | None:
    import shutil

    return shutil.which(command)


def _split_target(target: str) -> tuple[str, str]:
    if "@" not in target:
        raise AdapterError("SSH target must use user@host notation")
    return target.rsplit("@", 1)


def _split_destination(destination: str) -> tuple[str, str]:
    if ":" not in destination:
        raise AdapterError("remote destination must use user@host:path notation")
    return destination.rsplit(":", 1)


def _quote(value: str) -> str:
    import shlex

    return shlex.quote(value)
