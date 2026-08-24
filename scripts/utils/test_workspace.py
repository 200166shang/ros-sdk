import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.utils.workspace import changed_cpp_files


class ChangedCppFilesTests(unittest.TestCase):
    @patch("scripts.utils.workspace.Path.is_file", autospec=True)
    @patch("scripts.utils.workspace.subprocess.run")
    def test_returns_existing_cpp_files_under_src(
        self,
        run: unittest.mock.Mock,
        is_file: unittest.mock.Mock,
    ) -> None:
        run.return_value = subprocess.CompletedProcess(
            args=["git", "diff"],
            returncode=0,
            stdout="src/changed.cpp\nsrc/changed.hpp\nsrc/removed.cpp\ndocs/example.cpp\n",
            stderr="",
        )
        is_file.side_effect = lambda self: str(self) != "src/removed.cpp"

        self.assertEqual(
            changed_cpp_files("base-sha", "head-sha"),
            [Path("src/changed.cpp")],
        )
        run.assert_called_once_with(
            ["git", "diff", "--name-only", "base-sha", "head-sha"],
            check=True,
            capture_output=True,
            text=True,
        )

    @patch("scripts.utils.workspace.subprocess.run")
    def test_returns_empty_list_when_git_diff_fails(self, run: unittest.mock.Mock) -> None:
        run.side_effect = subprocess.CalledProcessError(128, ["git", "diff"])

        with self.assertRaises(subprocess.CalledProcessError):
            changed_cpp_files("base-sha", "head-sha")

    @patch("scripts.utils.workspace.DockerManager")
    @patch("scripts.utils.workspace.changed_cpp_files", return_value=[Path("src/changed.cpp")])
    @patch.dict("os.environ", {"PR_BASE_SHA": "base-sha", "PR_HEAD_SHA": "head-sha"})
    def test_lint_runs_parallel_tidy_for_changed_files(
        self,
        _changed_files: unittest.mock.Mock,
        docker_manager: unittest.mock.Mock,
    ) -> None:
        from scripts.utils.workspace import WorkspaceManager

        WorkspaceManager().lint()

        command = docker_manager.return_value.exec.call_args.args[2]
        self.assertIn("run-clang-tidy -j \"$(nproc)\"", command)
        self.assertIn("src/changed.cpp", command)


if __name__ == "__main__":
    unittest.main()
