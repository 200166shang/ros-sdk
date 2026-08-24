import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.ci.apply_conan_server_config import apply_config, update_server_config


class ApplyConanServerConfigTests(unittest.TestCase):
    def test_adds_exact_authorizer_without_rewriting_existing_permissions(self) -> None:
        current = """# production Conan server
[server]
port: 9300
jwt_secret: keep-me

[read_permissions]
*/*@*/*: *

[write_permissions]
*/*@*/*: publisher

[users]
maintainer: existing-password
ros-sdk-ci-reader: old-password
"""
        updated = update_server_config(
            current,
            username="ros-sdk-ci-reader",
            password="new-generated-password",
        )

        self.assertIn("# production Conan server", updated)
        self.assertIn("jwt_secret: keep-me", updated)
        self.assertIn("custom_authorizer: rosbridge_exact_reader", updated)
        self.assertIn("*/*@*/*: *", updated)
        self.assertIn("[write_permissions]\n*/*@*/*: publisher", updated)
        self.assertIn("maintainer: existing-password", updated)
        self.assertIn("ros-sdk-ci-reader: new-generated-password", updated)
        self.assertNotIn("old-password", updated)

    def test_apply_creates_backup_and_preserves_config_mode(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "server.conf"
            config.write_text(
                "[server]\nport: 9300\n\n"
                "[read_permissions]\n*/*@*/*: *\n\n"
                "[write_permissions]\n\n"
                "[users]\nmaintainer: existing\n",
                encoding="utf-8",
            )
            config.chmod(0o640)
            password = root / "password"
            password.write_text("generated-password\n", encoding="utf-8")
            plugin = root / "plugin.py"
            plugin.write_text("def get_class():\n    return object()\n", encoding="utf-8")
            policy = root / "policy.json"
            policy.write_text('{"schema_version": 1}\n', encoding="utf-8")

            backup = apply_config(config, "ci-reader", password, plugin, policy)

            self.assertTrue(backup.exists())
            self.assertIn("*/*@*/*: *", backup.read_text(encoding="utf-8"))
            self.assertIn("ci-reader: generated-password", config.read_text(encoding="utf-8"))
            self.assertEqual(config.stat().st_mode & 0o777, 0o640)
            plugin_dir = root / "plugins" / "authorizer"
            self.assertEqual(
                (plugin_dir / "rosbridge_exact_reader.py").read_text(encoding="utf-8"),
                plugin.read_text(encoding="utf-8"),
            )
            self.assertEqual(
                (plugin_dir / "rosbridge_exact_reader_policy.json").read_text(
                    encoding="utf-8"
                ),
                policy.read_text(encoding="utf-8"),
            )

    def test_overlap_rotation_preserves_existing_conan_password(self) -> None:
        current = (
            "[server]\nport: 9300\n\n"
            "[read_permissions]\n*/*@*/*: *\n\n"
            "[write_permissions]\n\n"
            "[users]\nros-sdk-ci-reader: existing-password\n"
        )

        updated = update_server_config(
            current,
            username="ros-sdk-ci-reader",
            password=None,
        )

        self.assertIn("ros-sdk-ci-reader: existing-password", updated)

    def test_does_not_overwrite_an_unrelated_custom_authorizer(self) -> None:
        current = (
            "[server]\ncustom_authorizer: company_policy\n\n"
            "[read_permissions]\n*/*@*/*: *\n\n"
            "[write_permissions]\n\n[users]\nmaintainer: password\n"
        )

        with self.assertRaisesRegex(ValueError, "different custom authorizer"):
            update_server_config(
                current,
                username="ros-sdk-ci-reader",
                password="new-password",
            )


if __name__ == "__main__":
    unittest.main()
