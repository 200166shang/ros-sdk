import os
import unittest
from unittest import mock

from scripts.utils.docker import DockerManager


class DockerManagerTests(unittest.TestCase):
    @mock.patch.object(DockerManager, "_detect_compose", return_value=["docker", "compose"])
    @mock.patch.dict(os.environ, {"COMPOSE_PROJECT_NAME": "ci-spike"}, clear=True)
    def test_uses_compose_project_from_environment(
        self, _detect_compose: mock.Mock
    ) -> None:
        manager = DockerManager()

        with mock.patch("scripts.utils.docker.subprocess.run") as run:
            manager.exec("bash", "-lc", "true")

        command = run.call_args.args[0]
        self.assertEqual(command[4:6], ["-p", "ci-spike"])

    @mock.patch.object(DockerManager, "_detect_compose", return_value=["docker", "compose"])
    @mock.patch.dict(os.environ, {}, clear=True)
    def test_keeps_default_compose_project_without_environment(
        self, _detect_compose: mock.Mock
    ) -> None:
        manager = DockerManager()

        with mock.patch("scripts.utils.docker.subprocess.run") as run:
            manager.ps()

        command = run.call_args.args[0]
        self.assertEqual(command[4:6], ["-p", "rosbridge"])


if __name__ == "__main__":
    unittest.main()
