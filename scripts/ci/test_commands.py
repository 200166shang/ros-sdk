import unittest

from scripts.ci.commands import environment_changed, select_ci_image


class CiCommandTests(unittest.TestCase):
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
