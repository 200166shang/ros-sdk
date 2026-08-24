"""Build, test, and lint helpers that run inside the ros2 container."""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path

from scripts.utils.docker import DockerManager


def changed_cpp_files(base_sha: str, head_sha: str) -> list[Path]:
    """Return existing source .cpp files changed between two commits."""
    result = subprocess.run(
        ["git", "diff", "--name-only", base_sha, head_sha],
        check=True,
        capture_output=True,
        text=True,
    )
    return [
        path
        for path in (Path(line) for line in result.stdout.splitlines())
        if path.parts and path.parts[0] == "src" and path.suffix == ".cpp" and path.is_file()
    ]


class WorkspaceManager:
    """Run colcon / conan / lint commands inside the ros2 container."""

    def __init__(self) -> None:
        self._docker = DockerManager()

    # -- build ---------------------------------------------------------------

    def build(self, clean: bool = False) -> None:
        """Run full build: conan install + colcon build."""
        command = ["python3", "-m", "scripts.ci", "build-workspace"]
        if clean:
            command.append("--clean")
        self._docker.exec(*command)

    def test(self, filter_pattern: str | None = None) -> None:
        """Run colcon test, optionally filtering test names."""
        cmd = "colcon test --base-paths src"
        if filter_pattern:
            cmd += f" --ctest-args -R '{filter_pattern}'"
        self._docker.exec("bash", "-c", f"{cmd} && colcon test-result --verbose")

    # -- lint ----------------------------------------------------------------

    def lint(self) -> None:
        """Run full clang-format and incremental clang-tidy for PR changes."""
        base_sha = os.environ.get("PR_BASE_SHA")
        head_sha = os.environ.get("PR_HEAD_SHA")
        changed_files = (
            changed_cpp_files(base_sha, head_sha) if base_sha and head_sha else []
        )
        if changed_files:
            changed_file_args = shlex.join(str(path) for path in changed_files)
            tidy_command = (
                "compile_db=$(find build -name compile_commands.json -print -quit); "
                "if [ -z \"$compile_db\" ]; then "
                "echo 'No compile_commands.json found — run ./rb build first'; exit 1; fi; "
                f"echo 'Running clang-tidy on {len(changed_files)} changed .cpp file(s):'; "
                f"printf '  %s\\n' {changed_file_args}; "
                "echo \"clang-tidy parallel jobs: $(nproc)\"; "
                "run-clang-tidy -j \"$(nproc)\" "
                "-p \"$(dirname \"$compile_db\")\" "
                f"{changed_file_args}"
            )
        else:
            message = (
                "No PR base/head SHA — skipping clang-tidy"
                if not base_sha or not head_sha
                else "No changed .cpp files — skipping clang-tidy"
            )
            tidy_command = f"echo '{message}';"

        self._docker.exec(
            "bash", "-c",
            "set -e; "
            "src_files=$(find src -type f \\( -name '*.hpp' -o -name '*.cpp' -o -name "
            "'*.h' \\) -print -quit); "
            "if [ -z \"$src_files\" ]; then "
            "echo 'No C++ source files found — skipping lint'; exit 0; fi; "
            "find src -type f \\( -name '*.hpp' -o -name '*.cpp' -o -name '*.h' \\) "
            "-print0 | xargs -0 clang-format --dry-run --Werror; " + tidy_command,
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
