import subprocess
import unittest
from unittest import mock

from scripts.ci import commands


class CiCommandTests(unittest.TestCase):
    def test_conan_install_command_preserves_defaults(self) -> None:
        command = commands.conan_install_command({})

        self.assertIn("--build=missing", command)
        self.assertNotIn("-cc", command)
        self.assertNotIn("--format=json", command)

    def test_conan_install_command_adds_spike_controls(self) -> None:
        command = commands.conan_install_command(
            {
                "CONAN_BUILD_POLICY": "never",
                "CONAN_DOWNLOAD_CACHE": "/workspace/.cache/conan-download",
                "CONAN_GRAPH_FILE": "/workspace/.cache/conan-spike/install-graph.json",
            }
        )

        self.assertIn("--build=never", command)
        self.assertIn("-cc", command)
        self.assertIn(
            "core.download:download_cache=/workspace/.cache/conan-download",
            command,
        )
        self.assertIn("--format=json", command)
        self.assertIn(
            "--out-file=/workspace/.cache/conan-spike/install-graph.json",
            command,
        )

    def test_conan_install_command_rejects_relative_download_cache(self) -> None:
        with self.assertRaisesRegex(ValueError, "absolute"):
            commands.conan_install_command(
                {"CONAN_DOWNLOAD_CACHE": ".cache/conan-download"}
            )

    def test_conan_install_command_rejects_unknown_build_policy(self) -> None:
        with self.assertRaisesRegex(ValueError, "CONAN_BUILD_POLICY"):
            commands.conan_install_command({"CONAN_BUILD_POLICY": "always"})

    @mock.patch.dict(commands.os.environ, {"CONAN_REQUIRE_REMOTE": "true"}, clear=True)
    def test_strict_conan_remote_requires_url(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "CONAN_REMOTE_URL"):
            commands._configure_conan_remote()

    @mock.patch.dict(
        commands.os.environ,
        {
            "CONAN_REQUIRE_REMOTE": "true",
            "CONAN_REMOTE_URL": "https://conan.example.test",
        },
        clear=True,
    )
    def test_strict_conan_remote_requires_credentials(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "credentials"):
            commands._configure_conan_remote()

    @mock.patch.dict(
        commands.os.environ,
        {
            "CONAN_REQUIRE_REMOTE": "true",
            "CONAN_REMOTE_URL": "https://conan.example.test",
            "CONAN_LOGIN_USERNAME": "ci",
            "CONAN_PASSWORD": "secret",
        },
        clear=True,
    )
    @mock.patch.object(commands, "_try_run", return_value=True)
    @mock.patch.object(
        commands,
        "_run",
        side_effect=subprocess.CalledProcessError(1, ["conan", "remote", "add"]),
    )
    def test_strict_conan_remote_reports_setup_failure(
        self, run: mock.Mock, try_run: mock.Mock
    ) -> None:
        with self.assertRaisesRegex(RuntimeError, "setup"):
            commands._configure_conan_remote()

    @mock.patch.dict(
        commands.os.environ,
        {"CONAN_BUILD_POLICY": "never"},
        clear=True,
    )
    @mock.patch.object(
        commands,
        "_run",
        side_effect=subprocess.CalledProcessError(1, ["conan", "install"]),
    )
    def test_never_policy_install_failure_requires_arm64_preparation(
        self, run: mock.Mock
    ) -> None:
        with self.assertRaisesRegex(
            RuntimeError, "ARM64 dependency preparation required"
        ):
            commands._install_conan_dependencies()

    @mock.patch.dict(
        commands.os.environ,
        {
            "COMPOSE_NO_DEPS": "TrUe",
            "COMPOSE_PROJECT_NAME": "conan-cache-spike",
            "COMPOSE_SERVICE": "ros2",
        },
        clear=True,
    )
    @mock.patch.object(commands, "_run")
    @mock.patch.object(commands, "_compose_command", return_value=["docker", "compose"])
    def test_compose_up_adds_no_deps_when_enabled(
        self, compose_command: mock.Mock, run: mock.Mock
    ) -> None:
        commands.compose_up()

        run.assert_called_once_with(
            [
                "docker",
                "compose",
                "--project-name",
                "conan-cache-spike",
                "up",
                "--detach",
                "--no-deps",
                "ros2",
            ]
        )

    @mock.patch.dict(commands.os.environ, {}, clear=True)
    @mock.patch.object(commands, "_run")
    @mock.patch.object(commands, "_compose_command", return_value=["docker", "compose"])
    def test_compose_up_omits_no_deps_by_default(
        self, compose_command: mock.Mock, run: mock.Mock
    ) -> None:
        commands.compose_up()

        command = run.call_args.args[0]
        self.assertNotIn("--no-deps", command)

    def test_environment_changes_when_build_inputs_change(self) -> None:
        self.assertTrue(commands.environment_changed(["conan.lock"]))
        self.assertTrue(commands.environment_changed(["docker/Dockerfile"]))
        self.assertTrue(commands.environment_changed(["src/ros2_sdk/CMakeLists.txt"]))

    def test_environment_does_not_change_for_source_only_edit(self) -> None:
        self.assertFalse(
            commands.environment_changed(["README.md", "src/ros2_sdk/src/foo.cpp"])
        )

    def test_select_ci_image_uses_cached_image_when_environment_is_unchanged(self) -> None:
        self.assertEqual(
            commands.select_ci_image(
                environment_changed=False,
                cache_available=True,
                cached_image="ghcr.io/example/ci-arm64-main",
                local_image="rosbridge:pr-ci-arm64",
            ),
            ("ghcr.io/example/ci-arm64-main", False),
        )

    def test_select_ci_image_builds_local_image_when_cache_is_missing(self) -> None:
        self.assertEqual(
            commands.select_ci_image(
                environment_changed=False,
                cache_available=False,
                cached_image="ghcr.io/example/ci-arm64-main",
                local_image="rosbridge:pr-ci-arm64",
            ),
            ("rosbridge:pr-ci-arm64", True),
        )

    def test_select_ci_image_builds_local_image_when_environment_changed(self) -> None:
        self.assertEqual(
            commands.select_ci_image(
                environment_changed=True,
                cache_available=True,
                cached_image="ghcr.io/example/ci-arm64-main",
                local_image="rosbridge:pr-ci-arm64",
            ),
            ("rosbridge:pr-ci-arm64", True),
        )


if __name__ == "__main__":
    unittest.main()
