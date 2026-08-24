import re
import unittest
from pathlib import Path


class ConanProvisioningContractTests(unittest.TestCase):
    def test_wizard_sets_every_secret_consumed_by_smoke_workflow(self) -> None:
        wizard = Path("scripts/provision_conan_ci.sh").read_text(encoding="utf-8")
        workflow = Path(".github/workflows/conan-access-smoke.yml").read_text(
            encoding="utf-8"
        )

        configured = set(
            re.findall(r"^\s*set_secret (CONAN_[A-Z_]+) ", wizard, re.MULTILINE)
        )
        consumed = set(re.findall(r"secrets\.(CONAN_[A-Z_]+)", workflow))

        self.assertEqual(configured, consumed)

    def test_wizard_does_not_persist_secrets_in_local_environment_file(self) -> None:
        wizard = Path("scripts/provision_conan_ci.sh").read_text(encoding="utf-8")
        stages = wizard.split("# STAGES:", maxsplit=1)[1]

        self.assertNotIn("write_env ", stages)
        self.assertIn("rm -rf \"$work_dir\"", stages)

    def test_smoke_workflow_is_manual_read_only_and_has_no_persistence(self) -> None:
        workflow = Path(".github/workflows/conan-access-smoke.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn("contents: read", workflow)
        self.assertIn("github.ref == 'refs/heads/main'", workflow)
        self.assertIn("ref: main", workflow)
        self.assertNotIn("pull_request", workflow)
        self.assertNotIn("upload-artifact", workflow)
        self.assertNotIn("actions/cache", workflow)
        self.assertRegex(workflow, r"ghcr\.io/.+@sha256:[0-9a-f]{64}")

        smoke = Path("scripts/ci/conan_access_smoke.sh").read_text(encoding="utf-8")
        self.assertIn("--request DELETE", smoke)
        self.assertIn("write_status == 403", smoke)


if __name__ == "__main__":
    unittest.main()
