import unittest
from unittest import mock

from scripts.ci import commands
from scripts.ci.commands import environment_changed, select_ci_image


class CiCommandTests(unittest.TestCase):
    def test_publish_image_pushes_moving_and_run_immutable_tags(self) -> None:
        with (
            mock.patch.dict(
                "os.environ",
                {
                    "CANDIDATE_IMAGE": "rosbridge:candidate",
                    "CI_IMAGE": "ghcr.io/example/ci-arm64-main",
                    "CI_IMAGE_IMMUTABLE": "ghcr.io/example/ci-arm64-deadbeef",
                },
                clear=True,
            ),
            mock.patch("scripts.ci.commands._run") as run,
        ):
            commands.publish_image()

        self.assertEqual(
            run.call_args_list,
            [
                mock.call(
                    [
                        "docker",
                        "tag",
                        "rosbridge:candidate",
                        "ghcr.io/example/ci-arm64-deadbeef",
                    ]
                ),
                mock.call(["docker", "push", "ghcr.io/example/ci-arm64-deadbeef"]),
                mock.call(
                    [
                        "docker",
                        "tag",
                        "rosbridge:candidate",
                        "ghcr.io/example/ci-arm64-main",
                    ]
                ),
                mock.call(["docker", "push", "ghcr.io/example/ci-arm64-main"]),
            ],
        )

    def test_environment_changes_when_build_inputs_change(self) -> None:
        self.assertTrue(environment_changed(["conan.lock"]))
        self.assertTrue(environment_changed(["docker/Dockerfile"]))
        self.assertTrue(environment_changed(["src/ros2_sdk/CMakeLists.txt"]))

    def test_environment_does_not_change_for_source_only_edit(self) -> None:
        self.assertFalse(
            environment_changed(["README.md", "src/ros2_sdk/src/foo.cpp"])
        )

    def test_select_ci_image_uses_cached_image_when_environment_is_unchanged(self) -> None:
        self.assertEqual(
            select_ci_image(
                environment_changed=False,
                cache_available=True,
                cached_image="ghcr.io/example/ci-arm64-main",
                local_image="rosbridge:pr-ci-arm64",
            ),
            ("ghcr.io/example/ci-arm64-main", False),
        )

    def test_select_ci_image_builds_local_image_when_cache_is_missing(self) -> None:
        self.assertEqual(
            select_ci_image(
                environment_changed=False,
                cache_available=False,
                cached_image="ghcr.io/example/ci-arm64-main",
                local_image="rosbridge:pr-ci-arm64",
            ),
            ("rosbridge:pr-ci-arm64", True),
        )

    def test_select_ci_image_builds_local_image_when_environment_changed(self) -> None:
        self.assertEqual(
            select_ci_image(
                environment_changed=True,
                cache_available=True,
                cached_image="ghcr.io/example/ci-arm64-main",
                local_image="rosbridge:pr-ci-arm64",
            ),
            ("rosbridge:pr-ci-arm64", True),
        )


if __name__ == "__main__":
    unittest.main()
