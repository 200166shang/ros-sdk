"""Observable workflow contracts for trusted cache production and read-only canaries."""

from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PRODUCER = ROOT / ".github" / "workflows" / "conan-cache-producer.yml"
CANARY = ROOT / ".github" / "workflows" / "conan-cache-canary.yml"
PR_CHECKS = ROOT / ".github" / "workflows" / "pr-checks.yml"
TUNNEL_RUNNER = ROOT / "scripts" / "ci" / "conan_cache_tunnel.sh"


class CacheWorkflowContractTests(unittest.TestCase):
    def test_trusted_producer_is_the_only_new_cache_writer(self) -> None:
        producer = PRODUCER.read_text(encoding="utf-8")
        canary = CANARY.read_text(encoding="utf-8")

        self.assertIn("push:", producer)
        self.assertIn("- main", producer)
        self.assertIn("workflow_dispatch:", producer)
        self.assertNotIn("pull_request", producer)
        self.assertNotIn("pull_request_target", producer)
        self.assertIn("actions: write", producer)
        self.assertIn("actions/cache/restore@v4", producer)
        self.assertIn("actions/cache/save@v4", producer)
        self.assertIn("steps.evidence.outputs.save_allowed == 'true'", producer)
        self.assertIn("github.ref == 'refs/heads/main'", producer)

        self.assertNotIn("actions/cache/save", canary)
        self.assertNotIn("actions: write", canary)

    def test_canary_restores_exact_then_compatible_and_never_replaces_pr_gate(self) -> None:
        canary = CANARY.read_text(encoding="utf-8")
        pr_checks = PR_CHECKS.read_text(encoding="utf-8")

        self.assertIn("workflow_dispatch:", canary)
        self.assertIn("sample_role:", canary)
        self.assertIn("cache_generation:", canary)
        self.assertIn("actions: read", canary)
        self.assertIn("actions/cache/restore@v4", canary)
        self.assertIn("key: ${{ steps.identity.outputs.key }}", canary)
        self.assertIn("restore-keys: ${{ steps.identity.outputs.restore_prefix }}", canary)
        self.assertIn("scripts/ci/conan_cache_tunnel.sh", canary)
        self.assertIn("github.ref == 'refs/heads/main'", canary)
        self.assertNotIn("pull_request_target", canary)
        self.assertNotIn("conan_cache_tunnel.sh", pr_checks)

    def test_both_workflows_emit_bounded_credential_free_evidence(self) -> None:
        for path in (PRODUCER, CANARY):
            with self.subTest(path=path.name):
                workflow = path.read_text(encoding="utf-8")
                self.assertIn("cache-identity", workflow)
                self.assertIn("conan-cache-${{ github.run_id }}", workflow)
                self.assertIn("retention-days: 7", workflow)
                self.assertIn("CONAN_SSH_PRIVATE_KEY: ${{ secrets.CONAN_SSH_PRIVATE_KEY }}", workflow)
                self.assertIn("CONAN_PASSWORD: ${{ secrets.CONAN_PASSWORD }}", workflow)


class CacheTunnelRunnerTests(unittest.TestCase):
    def test_missing_secret_configuration_fails_before_side_effects(self) -> None:
        completed = subprocess.run(
            [str(TUNNEL_RUNNER)],
            cwd=ROOT,
            env={"PATH": os.environ["PATH"]},
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 2)
        self.assertIn("required environment is not configured", completed.stderr)

    def test_runner_uses_strict_ephemeral_tunnel_and_container_boundaries(self) -> None:
        runner = TUNNEL_RUNNER.read_text(encoding="utf-8")

        self.assertIn("mktemp -d", runner)
        self.assertIn("trap cleanup EXIT HUP INT TERM", runner)
        self.assertIn("StrictHostKeyChecking=yes", runner)
        self.assertIn("ExitOnForwardFailure=yes", runner)
        self.assertIn("--network host", runner)
        self.assertIn("--tmpfs /tmp:", runner)
        self.assertIn("python3 -m scripts.ci cache-run", runner)
        self.assertNotIn("echo \"$CONAN_PASSWORD\"", runner)


if __name__ == "__main__":
    unittest.main()
