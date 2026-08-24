"""Readable orchestration model for Conan CI access provisioning.

The shell entry point remains intentionally small.  This module owns the
seven-step Conan CI access provisioning flow; the data objects below keep the
inputs and temporary artifacts visible while the flow is running.
"""

from __future__ import annotations

import base64
import argparse
import json
import secrets
import shutil
import shlex
import tempfile
from datetime import date, timedelta, datetime, timezone
from dataclasses import dataclass, field
from pathlib import Path

from scripts.ci.conan_access import render_policy_bundle


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
    emergency_ssh_user: str
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


class ProvisioningError(RuntimeError):
    """A user-facing failure that stops the provisioning flow."""


class ConsoleUi:
    """The small terminal interface used by the shell entry point."""

    def __init__(self, environment_file: Path) -> None:
        self.environment_file = environment_file
        self._stage_number = 0

    def banner(self) -> None:
        print("\n  Restricted Conan CI access")
        print(f"  {len(STAGE_NAMES)} stages\n")
        print("  You drive the browser; this wizard tells you exactly what to do and")
        print("  captures the values you copy back. Stop any time with Ctrl-C and re-run")
        print("  later, since it remembers values already saved.\n")
        self.pause("Ready to start?")

    def stage(self, title: str) -> None:
        self._stage_number += 1
        print(f"\n▸ Stage {self._stage_number}/{len(STAGE_NAMES)} · {title}\n")

    def say(self, message: str) -> None:
        print(f"  {message}")

    def step(self, message: str) -> None:
        print(f"  • {message}")

    def note(self, message: str) -> None:
        print(f"  {message}")

    def warn(self, message: str) -> None:
        print(f"  ⚠ {message}")

    def pause(self, message: str = "Press Enter to continue") -> None:
        input(f"  {message} ")

    def confirm(self, question: str) -> bool:
        return input(f"  ? {question} [y/N] ").strip().lower().startswith("y")

    def ask(self, key: str, prompt: str) -> str:
        current = self._existing(key)
        suffix = " [Enter keeps current]" if current else ""
        value = input(f"  {prompt}{suffix} ")
        return value or current

    def ask_default(self, prompt: str, default: str) -> str:
        value = input(f"  {prompt} [{default}] ")
        return value or default

    def show_file(self, path: Path) -> None:
        for line in path.read_text(encoding="utf-8").splitlines():
            print(f"  {line}")

    def finish(self, artifacts: ProvisioningArtifacts, environment_file: Path) -> None:
        print("\n  ✓ Setup complete")
        if artifacts.written_secrets:
            self.note(f"set {len(artifacts.written_secrets)} GitHub secret(s): "
                      f"{' '.join(artifacts.written_secrets)}")
        if artifacts.skipped_actions:
            print("\n  ⚠ still to do by hand:")
            for action in artifacts.skipped_actions:
                self.note(f"  - {action}")
        self.note(f"Temporary files will be deleted; no credentials were written to {environment_file}.")

    def _existing(self, key: str) -> str:
        if not self.environment_file.exists():
            return ""
        prefix = f"{key}="
        values = [
            line[len(prefix):]
            for line in self.environment_file.read_text(encoding="utf-8").splitlines()
            if line.startswith(prefix)
        ]
        return values[-1] if values else ""


class CommandAdapter:
    """One seam around local subprocess calls."""

    def run(self, args: list[str], **kwargs: object):
        import subprocess

        return subprocess.run(args, **kwargs)

    def require_commands(self) -> None:
        _require_commands()


class SshAdapter:
    """SSH and SCP operations used by the provisioning stages."""

    def __init__(self, commands: CommandAdapter) -> None:
        self.commands = commands

    def run_remote(
        self,
        target: str,
        port: int,
        command: str,
        *,
        check: bool = True,
    ):
        return self.commands.run(
            ["ssh", "-p", str(port), target, command],
            check=check,
        )

    def copy_to(self, paths: list[Path], target: str, port: int) -> None:
        self.commands.run(
            ["scp", "-P", str(port), *(str(path) for path in paths), target],
            check=True,
        )

    def scan_host(self, host: str, port: int) -> str:
        result = self.commands.run(
            ["ssh-keyscan", "-p", str(port), host],
            check=True,
            capture_output=True,
            text=True,
        )
        if not result.stdout.strip():
            raise ProvisioningError("no SSH host keys received")
        return result.stdout

    def show_fingerprints(self, known_hosts: Path) -> str:
        result = self.commands.run(
            ["ssh-keygen", "-lf", str(known_hosts)],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()


class GitHubAdapter:
    """The GitHub CLI operations used by stages six and seven."""

    def __init__(self, commands: CommandAdapter) -> None:
        self.commands = commands

    def authenticate(self) -> bool:
        result = self.commands.run(["gh", "auth", "status"], check=False)
        return result.returncode == 0

    def set_secret(self, name: str, value: str) -> bool:
        result = self.commands.run(
            ["gh", "secret", "set", name],
            input=value,
            text=True,
            check=False,
        )
        return result.returncode == 0

    def set_variable(self, name: str, value: str) -> bool:
        result = self.commands.run(
            ["gh", "variable", "set", name, "--body", value],
            check=False,
        )
        return result.returncode == 0

    def default_branch(self) -> str:
        result = self.commands.run(
            ["gh", "repo", "view", "--json", "defaultBranchRef", "--jq", ".defaultBranchRef.name"],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    def dispatch_smoke(self, workflow: str, branch: str, nonce: str) -> None:
        self.commands.run(
            ["gh", "workflow", "run", workflow, "--ref", branch, "-f", f"nonce={nonce}"],
            check=True,
        )

    def wait_for_smoke_run(
        self,
        workflow: str,
        branch: str,
        nonce: str,
        *,
        attempts: int = 10,
        delay_seconds: float = 2,
    ) -> int:
        import json
        import time

        expected_title = f"Conan Access Smoke {nonce}"
        for attempt in range(attempts):
            result = self.commands.run(
                [
                    "gh", "run", "list", "--workflow", workflow,
                    "--branch", branch, "--event", "workflow_dispatch",
                    "--limit", "20", "--json", "databaseId,displayTitle",
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
        raise ProvisioningError(f"could not find smoke workflow run: {expected_title}")

    def watch_run(self, run_id: int) -> None:
        self.commands.run(["gh", "run", "watch", str(run_id), "--exit-status"], check=True)


def collect_config(ui: ConsoleUi) -> ProvisioningConfig:
    """Collect the same values as the original wizard, in stage order."""
    server_admin_target = ui.ask("SERVER_ADMIN_TARGET", "Server admin SSH target (user@host):")
    server_admin_port = int(ui.ask_default("Server admin SSH port:", "22"))
    emergency_key_id = ui.ask(
        "EMERGENCY_KEY_ID",
        "Compromised key ID to revoke immediately (blank if none):",
    )
    emergency_ssh_user = ""
    if emergency_key_id:
        emergency_ssh_user = ui.ask_default("Dedicated tunnel OS user:", "rosbridge-conan-ci")
        if not ui.confirm(f"Immediately revoke {emergency_key_id} from {emergency_ssh_user}?"):
            raise ProvisioningError("emergency revocation was not confirmed")

    conan_ssh_host = ui.ask_default("Public SSH host:", "106.55.24.85")
    conan_ssh_port = int(ui.ask_default("Public SSH port:", "22"))
    ssh_user = ui.ask_default("Dedicated tunnel OS user:", "rosbridge-conan-ci")
    target_host = ui.ask_default("Conan endpoint as seen by sshd:", "127.0.0.1")
    target_port = int(ui.ask_default("Conan endpoint port:", "9300"))
    old_key_id = ui.ask(
        "OLD_KEY_ID",
        "Old key ID to remove after successful overlap rotation (blank for first setup):",
    )
    conan_server_config = ui.ask_default(
        "Conan Server config path:",
        "/root/.conan_server/server.conf",
    )
    conan_service = ui.ask_default("Conan Server systemd service:", "conan-server")
    return ProvisioningConfig(
        server_admin_target=server_admin_target,
        server_admin_port=server_admin_port,
        emergency_key_id=emergency_key_id,
        emergency_ssh_user=emergency_ssh_user,
        conan_ssh_host=conan_ssh_host,
        conan_ssh_port=conan_ssh_port,
        ssh_user=ssh_user,
        target_host=target_host,
        target_port=target_port,
        old_key_id=old_key_id,
        conan_server_config=conan_server_config,
        conan_service=conan_service,
    )


def _quote(value: str) -> str:
    return shlex.quote(value)


def _require_commands() -> None:
    for command in ("gh", "scp", "ssh", "ssh-keygen", "ssh-keyscan"):
        if shutil.which(command) is None:
            raise ProvisioningError(f"missing command: {command}")


def _load_conan_username(policy_path: Path) -> str:
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    username = str(policy.get("username", ""))
    if not username:
        raise ProvisioningError("the exact ARM64 package policy has no username")
    return username


def _write_secure(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o600)


def _render_bundle(
    artifacts: ProvisioningArtifacts,
    config: ProvisioningConfig,
    repo_root: Path,
    lockfile: Path,
    policy_path: Path,
    work_dir: Path,
) -> None:
    artifacts.policy_directory = work_dir / "policy"
    artifacts.policy_directory.mkdir(mode=0o700)
    render_policy_bundle(
        argparse.Namespace(
            public_key_file=str(artifacts.private_key) + ".pub",
            destination_host=config.target_host,
            destination_port=config.target_port,
            key_id=artifacts.key_id,
            ssh_user=config.ssh_user,
            lockfile=str(lockfile),
            package_policy=str(policy_path),
            output_directory=str(artifacts.policy_directory),
        )
    )


def _prepare_identity(
    artifacts: ProvisioningArtifacts,
    config: ProvisioningConfig,
    repo_root: Path,
    lockfile: Path,
    policy_path: Path,
    work_dir: Path,
    commands: CommandAdapter,
) -> None:
    timestamp = datetime.now(timezone.utc).date().isoformat()
    artifacts.key_id = f"ros-sdk-github-actions-{timestamp}-{secrets.token_hex(4)}"
    artifacts.private_key = work_dir / "id_ed25519"
    commands.run(
        [
            "ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C",
            artifacts.key_id, "-f", str(artifacts.private_key),
        ],
        check=True,
    )
    if not config.old_key_id or config.emergency_key_id:
        artifacts.conan_password = base64.b64encode(secrets.token_bytes(32)).decode()
    _write_secure(work_dir / "conan_password", artifacts.conan_password + "\n")
    _render_bundle(artifacts, config, repo_root, lockfile, policy_path, work_dir)


def _preflight(
    config: ProvisioningConfig,
    repo_root: Path,
    commands: CommandAdapter,
    ssh: SshAdapter,
    github: GitHubAdapter,
    ui: ConsoleUi,
) -> None:
    commands.require_commands()
    if not github.authenticate():
        raise ProvisioningError("authenticate gh before continuing")
    if not (repo_root / "conan.lock").is_file():
        raise ProvisioningError("run from the ros-sdk checkout")
    validate_config(config)
    if config.emergency_key_id:
        script = repo_root / "scripts/ci/apply_conan_ssh_policy.sh"
        remote_script = "/tmp/apply-conan-ssh-policy.sh"
        ssh.copy_to([script], f"{config.server_admin_target}:{remote_script}", config.server_admin_port)
        ssh.run_remote(
            config.server_admin_target,
            config.server_admin_port,
            "sudo bash {script} remove {user} {key}; rm -f {script}".format(
                script=_quote(remote_script),
                user=_quote(config.emergency_ssh_user),
                key=_quote(config.emergency_key_id),
            ),
        )
        ui.say("The suspected key was revoked before any replacement was created.")


def _host_identity(
    config: ProvisioningConfig,
    artifacts: ProvisioningArtifacts,
    work_dir: Path,
    ssh: SshAdapter,
    ui: ConsoleUi,
) -> None:
    assert artifacts.known_hosts is not None
    host_keys = ssh.scan_host(config.conan_ssh_host, config.conan_ssh_port)
    artifacts.known_hosts.write_text(host_keys, encoding="utf-8")
    artifacts.known_hosts.chmod(0o600)
    ui.say(ssh.show_fingerprints(artifacts.known_hosts))
    if not ui.confirm(
        "Do these fingerprints exactly match the independently verified server fingerprints?"
    ):
        raise ProvisioningError("host fingerprint verification was not confirmed")
    ui.say("Host verification material will be stored only as a GitHub Secret.")


def _server_ssh_policy(
    config: ProvisioningConfig,
    artifacts: ProvisioningArtifacts,
    repo_root: Path,
    ssh: SshAdapter,
    ui: ConsoleUi,
) -> None:
    assert artifacts.policy_directory is not None
    artifacts.remote_directory = f"/tmp/ros-sdk-conan-{artifacts.key_id}"
    remote = f"{config.server_admin_target}:{artifacts.remote_directory}/"
    ssh.run_remote(
        config.server_admin_target,
        config.server_admin_port,
        f"mkdir -m 700 {_quote(artifacts.remote_directory)}",
    )
    ssh.copy_to(
        [
            repo_root / "scripts/ci/apply_conan_ssh_policy.sh",
            artifacts.policy_directory / "authorized_key",
            artifacts.policy_directory / "sshd_config",
        ],
        remote,
        config.server_admin_port,
    )
    ui.step("Review the generated authorized_keys and sshd Match policy shown below.")
    ui.show_file(artifacts.policy_directory / "authorized_key")
    ui.show_file(artifacts.policy_directory / "sshd_config")
    if not ui.confirm("Install this dedicated account policy and reload sshd?"):
        raise ProvisioningError("server SSH policy was not confirmed")
    ssh.run_remote(
        config.server_admin_target,
        config.server_admin_port,
        "sudo bash {script} install {user} {key} {remote}".format(
            script=_quote(f"{artifacts.remote_directory}/apply_conan_ssh_policy.sh"),
            user=_quote(config.ssh_user),
            key=_quote(artifacts.key_id),
            remote=_quote(artifacts.remote_directory),
        ),
    )
    ui.say("The account has no login shell; sshd also denies PTY, agent/X11, remote and arbitrary forwarding.")


def _conan_identity(
    config: ProvisioningConfig,
    artifacts: ProvisioningArtifacts,
    repo_root: Path,
    ssh: SshAdapter,
    ui: ConsoleUi,
) -> None:
    assert artifacts.policy_directory is not None
    policy_file = artifacts.policy_directory / "conan_policy.json"
    ui.say("A custom authorizer limits this user to exact recipe revisions and ARM64 package IDs.")
    ui.say("Every other user continues through the server's existing read/write ACLs unchanged.")
    ui.step("Review the exact package policy shown below.")
    ui.show_file(policy_file)
    if not ui.confirm("Install the exact-package authorizer and add the dedicated reader?"):
        raise ProvisioningError("exact-package authorizer was not confirmed")
    ssh.copy_to(
        [
            repo_root / "scripts/ci/apply_conan_server_config.py",
            repo_root / "scripts/ci/conan_exact_reader_authorizer.py",
            policy_file,
            artifacts.private_key.parent / "conan_password"
            if artifacts.private_key
            else Path("conan_password"),
        ],
        f"{config.server_admin_target}:{artifacts.remote_directory}/",
        config.server_admin_port,
    )
    ssh.run_remote(
        config.server_admin_target,
        config.server_admin_port,
        "sudo python3 {updater} --config {config} --username {username} "
        "--password-file {password} --plugin {plugin} --policy {policy}".format(
            updater=_quote(f"{artifacts.remote_directory}/apply_conan_server_config.py"),
            config=_quote(config.conan_server_config),
            username=_quote(artifacts.conan_username),
            password=_quote(f"{artifacts.remote_directory}/conan_password"),
            plugin=_quote(f"{artifacts.remote_directory}/conan_exact_reader_authorizer.py"),
            policy=_quote(f"{artifacts.remote_directory}/conan_policy.json"),
        ),
    )
    restart = ssh.run_remote(
        config.server_admin_target,
        config.server_admin_port,
        f"sudo systemctl restart {_quote(config.conan_service)}",
        check=False,
    )
    if restart.returncode != 0:
        ui.warn("The config is updated, but systemd could not restart the Conan service.")
        ui.pause("Restart Conan Server through its real supervisor, then press Enter.")


def _repository_secrets(
    config: ProvisioningConfig,
    artifacts: ProvisioningArtifacts,
    github: GitHubAdapter,
    ui: ConsoleUi,
) -> None:
    assert artifacts.private_key is not None
    assert artifacts.known_hosts is not None
    secret_values = {
        "CONAN_SSH_PRIVATE_KEY": artifacts.private_key.read_text(encoding="utf-8"),
        "CONAN_SSH_KNOWN_HOSTS": artifacts.known_hosts.read_text(encoding="utf-8"),
        "CONAN_SSH_HOST": config.conan_ssh_host,
        "CONAN_SSH_PORT": str(config.conan_ssh_port),
        "CONAN_SSH_USER": config.ssh_user,
        "CONAN_SSH_TARGET_HOST": config.target_host,
        "CONAN_SSH_TARGET_PORT": str(config.target_port),
        "CONAN_LOGIN_USERNAME": artifacts.conan_username,
    }
    if artifacts.conan_password:
        secret_values["CONAN_PASSWORD"] = artifacts.conan_password
    for name, value in secret_values.items():
        if github.set_secret(name, value):
            artifacts.written_secrets.append(name)
            ui.say(f"✓ set GitHub secret {name}")
        else:
            action = f"GitHub secret {name} (set it manually: gh secret set {name})"
            artifacts.skipped_actions.append(action)
            ui.warn(f"skipped GitHub secret {name}: gh not ready; set it later")
    artifacts.rotate_after = str(date.today() + timedelta(days=180))
    for name, value in {
        "CONAN_SSH_KEY_ID": artifacts.key_id,
        "CONAN_SSH_ROTATE_AFTER": artifacts.rotate_after,
    }.items():
        if not github.set_variable(name, value):
            artifacts.skipped_actions.append(f"GitHub variable {name}")
            ui.warn(f"skipped GitHub variable {name}, gh not ready; set it later")
    if artifacts.skipped_actions:
        raise ProvisioningError(
            "every repository secret and variable must be updated before smoke testing"
        )
    if not artifacts.conan_password:
        ui.say("Keeping the existing Conan password during overlap key rotation.")
    ui.say("Secrets were streamed to GitHub CLI and will be deleted from local temporary storage on exit.")


def _smoke_and_rotate(
    config: ProvisioningConfig,
    artifacts: ProvisioningArtifacts,
    repo_root: Path,
    ssh: SshAdapter,
    github: GitHubAdapter,
    ui: ConsoleUi,
) -> None:
    trusted_branch = github.default_branch()
    if trusted_branch != "main":
        raise ProvisioningError("trusted default branch must be main")
    nonce = f"provision-{artifacts.key_id}-{secrets.token_hex(4)}"
    github.dispatch_smoke("conan-access-smoke.yml", trusted_branch, nonce)
    run_id = github.wait_for_smoke_run("conan-access-smoke.yml", trusted_branch, nonce)
    github.watch_run(run_id)
    if config.old_key_id:
        if not ui.confirm(f"Smoke passed. Remove old key {config.old_key_id} now?"):
            raise ProvisioningError("old key removal was not confirmed")
        script = repo_root / "scripts/ci/apply_conan_ssh_policy.sh"
        remote_script = "/tmp/apply-conan-ssh-policy.sh"
        ssh.copy_to([script], f"{config.server_admin_target}:{remote_script}", config.server_admin_port)
        ssh.run_remote(
            config.server_admin_target,
            config.server_admin_port,
            "sudo bash {script} remove {user} {key}; rm -f {script}".format(
                script=_quote(remote_script),
                user=_quote(config.ssh_user),
                key=_quote(config.old_key_id),
            ),
        )
    ui.say(f"Rotate again by {artifacts.rotate_after}: add new key, update Secrets, verify, then remove this key.")
    ui.say("For suspected leakage, re-run and provide the compromised key ID in Stage 1 for immediate revocation.")


def _remove_remote_directory(
    config: ProvisioningConfig,
    artifacts: ProvisioningArtifacts,
    ssh: SshAdapter,
) -> None:
    if not artifacts.remote_directory:
        return
    ssh.run_remote(
        config.server_admin_target,
        config.server_admin_port,
        f"rm -rf {_quote(artifacts.remote_directory)}",
        check=False,
    )
    artifacts.remote_directory = ""


def run_provisioning(
    config: ProvisioningConfig | None = None,
    *,
    repo_root: Path | None = None,
    ui: ConsoleUi | None = None,
    commands: CommandAdapter | None = None,
    ssh: SshAdapter | None = None,
    github: GitHubAdapter | None = None,
) -> ProvisioningArtifacts:
    """Run the seven Conan CI access stages in a fixed, readable order."""
    root = repo_root or Path(__file__).resolve().parents[2]
    terminal = ui or ConsoleUi(root / ".env")
    command_adapter = commands or CommandAdapter()
    ssh_adapter = ssh or SshAdapter(command_adapter)
    github_adapter = github or GitHubAdapter(command_adapter)
    terminal.banner()
    terminal.stage(STAGE_NAMES[0])
    if config is None:
        config = collect_config(terminal)
    _preflight(config, root, command_adapter, ssh_adapter, github_adapter, terminal)
    policy_path = root / "scripts/ci/conan_arm64_packages.json"
    lockfile = root / "conan.lock"
    artifacts = ProvisioningArtifacts()
    try:
        terminal.stage(STAGE_NAMES[1])
        terminal.say("Dedicated Conan reader from exact ARM64 policy: "
                     f"{_load_conan_username(policy_path)}")
        _prepare_identity(artifacts, config, root, lockfile, policy_path, Path(tempfile.mkdtemp()), command_adapter)
        artifacts.conan_username = _load_conan_username(policy_path)
        terminal.say(f"Generated a fresh Ed25519 identity: {artifacts.key_id}")

        terminal.stage(STAGE_NAMES[2])
        # The identity directory is the parent of all temporary artifacts.
        work_dir = artifacts.private_key.parent if artifacts.private_key else Path(tempfile.mkdtemp())
        artifacts.known_hosts = work_dir / "known_hosts"
        _host_identity(config, artifacts, work_dir, ssh_adapter, terminal)

        terminal.stage(STAGE_NAMES[3])
        _server_ssh_policy(config, artifacts, root, ssh_adapter, terminal)

        terminal.stage(STAGE_NAMES[4])
        _conan_identity(config, artifacts, root, ssh_adapter, terminal)
        _remove_remote_directory(config, artifacts, ssh_adapter)

        terminal.stage(STAGE_NAMES[5])
        _repository_secrets(config, artifacts, github_adapter, terminal)

        terminal.stage(STAGE_NAMES[6])
        _smoke_and_rotate(config, artifacts, root, ssh_adapter, github_adapter, terminal)
        terminal.finish(artifacts, terminal.environment_file)
        return artifacts
    finally:
        _remove_remote_directory(config, artifacts, ssh_adapter)
        if artifacts.private_key:
            shutil.rmtree(artifacts.private_key.parent, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Provision restricted Conan CI access through a seven-stage wizard"
    )
    parser.parse_args(argv)
    try:
        run_provisioning()
    except (ProvisioningError, ValueError, OSError) as error:
        print(f"error: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
