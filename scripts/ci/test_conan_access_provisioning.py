import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.ci.conan_access_provisioning import (
    CommandAdapter,
    ConsoleUi,
    GitHubAdapter,
    ProvisioningConfig,
    SshAdapter,
    run_provisioning,
)


class FakeCommands(CommandAdapter):
    """Small fake for the one complete provisioning-flow test."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.nonce = ""

    def require_commands(self) -> None:
        return None

    def run(self, args: list[str], **kwargs: object):
        self.calls.append(args)
        if args[:2] == ["ssh-keygen", "-q"]:
            return subprocess.run(args, **kwargs)
        if args[:2] == ["ssh-keyscan", "-p"]:
            return subprocess.CompletedProcess(args, 0, stdout="host ssh-ed25519 AAAA\n")
        if args[:3] == ["ssh-keygen", "-lf", str(args[-1])]:
            return subprocess.CompletedProcess(args, 0, stdout="256 SHA256:test host (ED25519)\n")
        if args[:3] == ["gh", "auth", "status"]:
            return subprocess.CompletedProcess(args, 0)
        if args[:3] == ["gh", "repo", "view"]:
            return subprocess.CompletedProcess(args, 0, stdout="main\n")
        if args[:3] == ["gh", "workflow", "run"]:
            self.nonce = args[-1].split("=", maxsplit=1)[1]
        if args[:3] == ["gh", "run", "list"]:
            output = json.dumps([
                {"databaseId": 81, "displayTitle": f"Conan Access Smoke {self.nonce}"}
            ])
            return subprocess.CompletedProcess(args, 0, stdout=output)
        return subprocess.CompletedProcess(args, 0)


class QuietUi(ConsoleUi):
    def __init__(self, environment_file: Path) -> None:
        super().__init__(environment_file)
        self.stages: list[str] = []

    def banner(self) -> None:
        return None

    def stage(self, title: str) -> None:
        self.stages.append(title)

    def say(self, message: str) -> None:
        return None

    def step(self, message: str) -> None:
        return None

    def show_file(self, path: Path) -> None:
        return None

    def confirm(self, question: str) -> bool:
        return True

    def pause(self, message: str = "Press Enter to continue") -> None:
        return None

    def finish(self, artifacts, environment_file: Path) -> None:
        return None


class ConanAccessProvisioningFlowTests(unittest.TestCase):
    def test_complete_flow_runs_the_seven_stages_in_order(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        config = ProvisioningConfig(
            server_admin_target="admin@example.com",
            server_admin_port=22,
            emergency_key_id="",
            emergency_ssh_user="",
            conan_ssh_host="conan.example.com",
            conan_ssh_port=22,
            ssh_user="rosbridge-conan-ci",
            target_host="127.0.0.1",
            target_port=9300,
            old_key_id="",
            conan_server_config="/root/.conan_server/server.conf",
            conan_service="conan-server",
        )
        commands = FakeCommands()
        with tempfile.TemporaryDirectory() as temporary:
            ui = QuietUi(Path(temporary) / ".env")
            artifacts = run_provisioning(
                config,
                repo_root=repo_root,
                ui=ui,
                commands=commands,
                ssh=SshAdapter(commands),
                github=GitHubAdapter(commands),
            )

        self.assertEqual(len(ui.stages), 7)
        self.assertEqual(artifacts.conan_username, "ros-sdk-ci-reader")
        self.assertIn(["gh", "workflow", "run", "conan-access-smoke.yml", "--ref", "main", "-f"],
                      [call[:7] for call in commands.calls])


if __name__ == "__main__":
    unittest.main()
