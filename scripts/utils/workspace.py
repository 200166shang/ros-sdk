"""Build, test, and lint helpers that run inside the ros2 container."""

from __future__ import annotations

import sys

from scripts.utils.docker import DockerManager


class WorkspaceManager:
    """Run colcon / conan / lint commands inside the ros2 container."""

    def __init__(self) -> None:
        self._docker = DockerManager()

    # -- build ---------------------------------------------------------------

    def build(self, clean: bool = False) -> None:
        """Run full build: conan install + colcon build."""
        if clean:
            self._docker.exec("bash", "-c", "rm -rf build install log")
        self._docker.exec(
            "bash", "-c",
            "conan install . "
            "--output-folder=build "
            "--build=missing "
            "-s build_type=Release "
            "-s compiler.cppstd=17 "
            "&& . build/conanbuild.sh "
            "&& colcon build --symlink-install",
        )

    def test(self, filter_pattern: str | None = None) -> None:
        """Run colcon test, optionally filtering test names."""
        cmd = "colcon test"
        if filter_pattern:
            cmd += f" --ctest-args -R '{filter_pattern}'"
        self._docker.exec("bash", "-c", cmd)

    # -- lint ----------------------------------------------------------------

    def lint(self) -> None:
        """Run clang-format (dry-run) and clang-tidy."""
        self._docker.exec(
            "bash", "-c",
            "src_files=$(find packages -name '*.hpp' -o -name '*.cpp' -o -name "
            "'*.h' | head -1); "
            "if [ -z \"$src_files\" ]; then "
            "echo 'No source files found — skipping lint'; exit 0; fi; "
            "find packages \\( -name '*.hpp' -o -name '*.cpp' -o -name '*.h' \\) "
            "-print0 | xargs -0 clang-format --dry-run --Werror "
            "&& find packages \\( -name '*.hpp' -o -name '*.cpp' -o -name '*.h' \\) "
            "-print0 | xargs -0 clang-tidy -p build",
        )

    def format(self) -> None:
        """Apply clang-format in-place."""
        self._docker.exec(
            "bash", "-c",
            "find packages -name '*.hpp' -o -name '*.cpp' "
            "| xargs clang-format -i",
        )

    # -- ci ------------------------------------------------------------------

    def ci(self) -> None:
        """Run the full CI pipeline: lint → build → test."""
        stages = [
            ("Lint", self.lint),
            ("Build", self.build),
            ("Test", self.test),
        ]
        for name, stage in stages:
            print(f"\n=== {name} ===")
            try:
                stage()
            except SystemExit:
                print(f"ci: {name} stage failed", file=sys.stderr)
                sys.exit(1)
