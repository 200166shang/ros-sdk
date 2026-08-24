import unittest
import subprocess
import sys
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from scripts.ci.conan_access import (
    authorized_key_entry,
    load_exact_package_policy,
    wait_for_smoke_run,
    write_text_securely,
    sshd_match_block,
)


class ConanAccessPolicyTests(unittest.TestCase):
    def test_authorized_key_only_opens_the_conan_endpoint(self) -> None:
        entry = authorized_key_entry(
            "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITestKey maintainer@host",
            "127.0.0.1",
            9300,
            "ros-sdk-github-actions-2026-08-24",
        )

        self.assertEqual(
            entry,
            'restrict,port-forwarding,permitopen="127.0.0.1:9300" '
            "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITestKey "
            "ros-sdk-github-actions-2026-08-24",
        )

    def test_sshd_policy_only_allows_local_forwarding_to_conan(self) -> None:
        block = sshd_match_block("rosbridge-conan-ci", "127.0.0.1", 9300)

        self.assertEqual(
            block,
            "Match User rosbridge-conan-ci\n"
            "  AuthenticationMethods publickey\n"
            "  PasswordAuthentication no\n"
            "  KbdInteractiveAuthentication no\n"
            "  PubkeyAuthentication yes\n"
            "  PermitTTY no\n"
            "  X11Forwarding no\n"
            "  AllowAgentForwarding no\n"
            "  AllowTcpForwarding local\n"
            "  AllowStreamLocalForwarding no\n"
            "  PermitOpen 127.0.0.1:9300\n"
            "  PermitListen none\n"
            "  GatewayPorts no\n"
            "  PermitUserRC no\n",
        )

    def test_conan_policy_matches_locked_recipes_and_exact_arm64_packages(self) -> None:
        policy = load_exact_package_policy(
            Path("scripts/ci/conan_arm64_packages.json"), Path("conan.lock")
        )

        self.assertEqual(policy["profile"]["arch"], "armv8")
        self.assertIn(
            "grpc/1.82.0#854077a504a256205bdc03c1156bb782",
            policy["recipes"],
        )
        self.assertIn(
            "grpc/1.82.0#854077a504a256205bdc03c1156bb782:"
            "b8cf8d37e501e489e0eaa3b565846024f5a0065b#"
            "438557092d92ee51e6500c86d0a75d79",
            policy["packages"],
        )

    def test_policy_rejects_values_that_could_escape_configuration(self) -> None:
        with self.assertRaisesRegex(ValueError, "Ed25519"):
            authorized_key_entry(
                "ssh-rsa AAAABadKey", "127.0.0.1", 9300, "safe-key-id"
            )
        with self.assertRaisesRegex(ValueError, "destination host"):
            authorized_key_entry(
                "ssh-ed25519 AAAATestKey",
                '127.0.0.1",command="id"',
                9300,
                "safe-key-id",
            )
        with self.assertRaisesRegex(ValueError, "username"):
            sshd_match_block("ci-user\nMatch All", "127.0.0.1", 9300)
        with TemporaryDirectory() as directory:
            policy = json.loads(
                Path("scripts/ci/conan_arm64_packages.json").read_text(encoding="utf-8")
            )
            policy["profile"]["arch"] = "x86_64"
            policy_path = Path(directory) / "policy.json"
            policy_path.write_text(json.dumps(policy), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "ARM64"):
                load_exact_package_policy(policy_path, Path("conan.lock"))

    def test_policy_artifacts_are_owner_readable_only(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory) / "policy"
            write_text_securely(output, "sensitive policy\n")

            self.assertEqual(output.read_text(encoding="utf-8"), "sensitive policy\n")
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)

    def test_render_command_creates_the_complete_review_bundle(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            public_key = root / "id_ed25519.pub"
            public_key.write_text(
                "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITestKey local-comment\n",
                encoding="utf-8",
            )
            output = root / "bundle"

            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "scripts.ci.conan_access",
                    "render",
                    "--public-key-file",
                    str(public_key),
                    "--destination-host",
                    "127.0.0.1",
                    "--destination-port",
                    "9300",
                    "--key-id",
                    "ros-sdk-github-actions-2026-08-24",
                    "--ssh-user",
                    "rosbridge-conan-ci",
                    "--lockfile",
                    "conan.lock",
                    "--package-policy",
                    "scripts/ci/conan_arm64_packages.json",
                    "--output-directory",
                    str(output),
                ],
                check=True,
            )

            self.assertEqual(
                {path.name for path in output.iterdir()},
                {"authorized_key", "sshd_config", "conan_policy.json"},
            )
            self.assertIn(
                'permitopen="127.0.0.1:9300"',
                (output / "authorized_key").read_text(encoding="utf-8"),
            )
            self.assertIn(
                "AllowTcpForwarding local",
                (output / "sshd_config").read_text(encoding="utf-8"),
            )
            self.assertIn(
                "b8cf8d37e501e489e0eaa3b565846024f5a0065b",
                (output / "conan_policy.json").read_text(encoding="utf-8"),
            )

    @mock.patch("scripts.ci.conan_access.time.sleep")
    @mock.patch("scripts.ci.conan_access.subprocess.run")
    def test_wait_for_smoke_run_ignores_unrelated_dispatches(
        self, run: mock.Mock, sleep: mock.Mock
    ) -> None:
        run.side_effect = [
            subprocess.CompletedProcess(
                [], 0, stdout='[{"databaseId": 10, "displayTitle": "unrelated"}]'
            ),
            subprocess.CompletedProcess(
                [],
                0,
                stdout=(
                    '[{"databaseId": 11, "displayTitle": '
                    '"Conan Access Smoke provision-key-123"}]'
                ),
            ),
        ]

        run_id = wait_for_smoke_run(
            "conan-access-smoke.yml", "main", "provision-key-123", attempts=2
        )

        self.assertEqual(run_id, 11)
        self.assertEqual(run.call_count, 2)
        self.assertEqual(sleep.call_count, 1)
        command = run.call_args.args[0]
        self.assertIn("--branch", command)
        self.assertIn("main", command)


if __name__ == "__main__":
    unittest.main()
