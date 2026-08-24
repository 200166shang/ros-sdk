import re
import unittest
from pathlib import Path


class ConanProvisioningContractTests(unittest.TestCase):
    def test_wizard_sets_every_secret_consumed_by_smoke_workflow(self) -> None:
        provisioning = Path("scripts/ci/conan_access_provisioning.py").read_text(
            encoding="utf-8"
        )
        workflow = Path(".github/workflows/conan-access-smoke.yml").read_text(
            encoding="utf-8"
        )

        secret_block = provisioning.split("REPOSITORY_SECRET_NAMES = (", maxsplit=1)[1]
        secret_block = secret_block.split(")", maxsplit=1)[0]
        configured = set(re.findall(r'"(CONAN_[A-Z_]+)"', secret_block))
        consumed = set(re.findall(r"secrets\.(CONAN_[A-Z_]+)", workflow))

        self.assertEqual(configured, consumed)

    def test_wizard_does_not_persist_secrets_in_local_environment_file(self) -> None:
        wizard = Path("scripts/provision_conan_ci.sh").read_text(encoding="utf-8")
        provisioning = Path("scripts/ci/conan_access_provisioning.py").read_text(
            encoding="utf-8"
        )

        self.assertNotIn("write_env ", wizard)
        self.assertNotIn("write_env ", provisioning)
        self.assertIn("shutil.rmtree", provisioning)

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
