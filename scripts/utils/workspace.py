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
            "--lockfile=conan.lock "
            "--output-folder=build "
            "--build=missing "
            "-s build_type=Release "
            "-s compiler.cppstd=17 "
            "&& . build/conanbuild.sh "
            "&& colcon build --base-paths src --symlink-install "
            "--cmake-args "
            "-DCMAKE_TOOLCHAIN_FILE=/workspace/build/conan_toolchain.cmake "
            "-DCMAKE_BUILD_TYPE=Release "
            "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON",
        )

    def test(self, filter_pattern: str | None = None) -> None:
        """Run colcon test, optionally filtering test names."""
        cmd = "colcon test --base-paths src"
        if filter_pattern:
            cmd += f" --ctest-args -R '{filter_pattern}'"
        self._docker.exec("bash", "-c", f"{cmd} && colcon test-result --verbose")

    # -- lint ----------------------------------------------------------------

    def lint(self) -> None:
        """Run clang-format (dry-run) and clang-tidy."""
        self._docker.exec(
            "bash", "-c",
            "src_files=$(find src -type f \\( -name '*.hpp' -o -name '*.cpp' -o -name "
            "'*.h' \\) -print -quit); "
            "if [ -z \"$src_files\" ]; then "
            "echo 'No C++ source files found — skipping lint'; exit 0; fi; "
            "find src -type f \\( -name '*.hpp' -o -name '*.cpp' -o -name '*.h' \\) "
            "-print0 | xargs -0 clang-format --dry-run --Werror "
            "&& compile_db=$(find build -name compile_commands.json -print -quit); "
            "if [ -z \"$compile_db\" ]; then "
            "echo 'No compile_commands.json found — run ./rb build first'; exit 1; fi; "
            "find src -type f \\( -name '*.hpp' -o -name '*.cpp' -o -name '*.h' \\) "
            "-print0 | xargs -0 clang-tidy -p \"$(dirname \"$compile_db\")\"",
        )

    def format(self) -> None:
        """Apply clang-format in-place."""
        self._docker.exec(
            "bash", "-c",
            "src_files=$(find src -type f \\( -name '*.hpp' -o -name '*.cpp' -o -name "
            "'*.h' \\) -print -quit); "
            "if [ -z \"$src_files\" ]; then "
            "echo 'No C++ source files found — skipping format'; exit 0; fi; "
            "find src -type f \\( -name '*.hpp' -o -name '*.cpp' -o -name '*.h' \\) "
            "-print0 | xargs -0 clang-format -i",
        )

    # -- ci ------------------------------------------------------------------

    def ci(self) -> None:
        """Run the full CI pipeline: build → lint → test."""
        stages = [
            ("Build", self.build),
            ("Lint", self.lint),
            ("Test", self.test),
        ]
        for name, stage in stages:
            print(f"\n=== {name} ===")
            try:
                stage()
            except SystemExit:
                print(f"ci: {name} stage failed", file=sys.stderr)
                sys.exit(1)
