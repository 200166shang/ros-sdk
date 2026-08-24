"""Behavior tests for the shared CI orchestration boundary."""

from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import unittest
from unittest import mock

from scripts.ci.__main__ import main
from scripts.ci.orchestration import (
    CacheState,
    CommandResult,
    DependencyPath,
    EventType,
    ExecutionClass,
    FailureClass,
    GateRequest,
    build_strict_conan_command,
    classify_terminal_failure,
    create_execution_plan,
    run_dependency_gate,
)


class ExecutionPlanTests(unittest.TestCase):
    def test_source_pull_request_has_complete_warm_plan(self) -> None:
        plan = create_execution_plan(
            EventType.PULL_REQUEST,
            ["src/ros2_sdk/src/runtime_server.cpp", "README.md"],
            CacheState.HIT,
        )

        self.assertEqual(plan.execution_class, ExecutionClass.SOURCE_PULL_REQUEST)
        self.assertEqual(plan.environment_triggers, ())
        self.assertEqual(plan.dependency_path, DependencyPath.WARM)
        self.assertFalse(plan.publish_image)
        self.assertEqual(
            plan.phase_steps,
            (
                ("reuse-ci-image",),
                (
                    "restore-dependency-cache",
                    "verify-required-conan-remote",
                    "install-locked-arm64-dependencies",
                ),
                ("build",),
                ("lint", "test"),
            ),
        )

    def test_each_specified_environment_category_reports_its_input(self) -> None:
        cases = {
            "Dockerfile": "docker-environment",
            "docker/Dockerfile": "docker-environment",
            "docker-compose.yaml": "docker-environment",
            "conanfile.txt": "conan-dependencies",
            "components/example/conanfile.py": "conan-dependencies",
            "conan.lock": "conan-dependencies",
            "package.xml": "ros-cmake-dependencies",
            "src/ros2_sdk/package.xml": "ros-cmake-dependencies",
            "src/ros2_sdk/CMakeLists.txt": "ros-cmake-dependencies",
            "ci/profiles/arm64": "profile-fingerprint",
            ".github/workflows/pr-checks.yml": "ci-behavior",
            "scripts/utils/docker.py": "ci-behavior",
        }

        for path, category in cases.items():
            with self.subTest(path=path):
                plan = create_execution_plan(
                    EventType.PULL_REQUEST,
                    [path],
                    CacheState.MISS,
                )
                self.assertEqual(
                    plan.execution_class,
                    ExecutionClass.ENVIRONMENT_PULL_REQUEST,
                )
                self.assertEqual(plan.environment_triggers[0].path, path)
                self.assertEqual(plan.environment_triggers[0].category.value, category)
                self.assertEqual(plan.dependency_path, DependencyPath.COLD)
                self.assertEqual(plan.phase_steps[0], ("build-candidate-image",))
                self.assertFalse(plan.publish_image)

    def test_unknown_input_conservatively_enters_environment_path(self) -> None:
        plan = create_execution_plan(
            EventType.PULL_REQUEST,
            ["tooling/new-policy.data"],
            CacheState.MISS,
        )

        self.assertEqual(plan.execution_class, ExecutionClass.ENVIRONMENT_PULL_REQUEST)
        self.assertEqual(plan.environment_triggers[0].category.value, "ambiguous")
        self.assertIn("tooling/new-policy.data", plan.explanation)

    def test_post_merge_image_update_requires_actual_image_input(self) -> None:
        plan = create_execution_plan(
            EventType.MAIN_PUSH,
            ["docker/entrypoint.sh", "conan.lock"],
            CacheState.HIT,
        )

        self.assertEqual(plan.execution_class, ExecutionClass.POST_MERGE_IMAGE_UPDATE)
        self.assertTrue(plan.publish_image)
        self.assertEqual(plan.phase_steps[-2:], (("refresh-trusted-cache",), ("publish-ci-image",)))

    def test_main_ci_behavior_change_does_not_publish_an_image(self) -> None:
        plan = create_execution_plan(
            EventType.MAIN_PUSH,
            ["scripts/ci/commands.py"],
            CacheState.HIT,
        )

        self.assertEqual(plan.execution_class, ExecutionClass.NO_ACTION)
        self.assertFalse(plan.publish_image)
        self.assertEqual(plan.phase_steps, ())
        self.assertEqual(plan.environment_triggers[0].category.value, "ci-behavior")

    def test_cache_restore_failure_uses_only_strict_server_fallback(self) -> None:
        plan = create_execution_plan(
            EventType.PULL_REQUEST,
            ["src/ros2_sdk/src/runtime_server.cpp"],
            CacheState.RESTORE_FAILURE,
        )

        self.assertEqual(plan.dependency_path, DependencyPath.STRICT_SERVER_FALLBACK)
        dependency_steps = plan.phase_steps[1]
        self.assertNotIn("build-missing-dependencies", dependency_steps)
        self.assertEqual(
            dependency_steps,
            (
                "record-cache-service-failure",
                "verify-required-conan-remote",
                "install-locked-arm64-dependencies",
            ),
        )


class StrictConanCommandTests(unittest.TestCase):
    def test_command_locks_arm64_to_named_remote_without_source_builds(self) -> None:
        command = build_strict_conan_command(
            GateRequest(
                remote_name="rosbridge",
                cache_state=CacheState.MISS,
                download_cache="/workspace/.cache/conan-download",
                graph_output="/workspace/.cache/conan-canary/graph.json",
            )
        )

        self.assertIn("--remote=rosbridge", command)
        self.assertIn("--lockfile=conan.lock", command)
        self.assertIn("--settings:host=arch=armv8", command)
        self.assertIn("--settings:build=arch=armv8", command)
        self.assertIn("--settings:host=build_type=Release", command)
        self.assertIn("--settings:build=build_type=Release", command)
        self.assertIn("--settings:host=compiler.cppstd=17", command)
        self.assertIn("--settings:build=compiler.cppstd=17", command)
        self.assertIn("--build=never", command)
        self.assertNotIn("--build=missing", command)
        self.assertIn(
            "core.download:download_cache=/workspace/.cache/conan-download",
            command,
        )
        self.assertIn("--format=json", command)
        self.assertIn(
            "--out-file=/workspace/.cache/conan-canary/graph.json",
            command,
        )

    def test_command_requires_a_safe_remote_name(self) -> None:
        with self.assertRaisesRegex(ValueError, "remote"):
            build_strict_conan_command(
                GateRequest(
                    remote_name="https://user:password@example.invalid",
                    cache_state=CacheState.MISS,
                )
            )

    def test_command_rejects_relative_graph_output(self) -> None:
        with self.assertRaisesRegex(ValueError, "graph"):
            build_strict_conan_command(
                GateRequest(
                    remote_name="rosbridge",
                    cache_state=CacheState.MISS,
                    graph_output=".cache/graph.json",
                )
            )


class OrchestrationCliTests(unittest.TestCase):
    def test_plan_command_emits_machine_readable_complete_plan(self) -> None:
        stdout = io.StringIO()
        argv = [
            "scripts.ci",
            "plan",
            "--event",
            "pull-request",
            "--cache-state",
            "miss",
            "--changed-file",
            "conan.lock",
        ]

        with mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(stdout):
            exit_code = main()

        document = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(document["execution_class"], "environment-pull-request")
        self.assertEqual(document["dependency_path"], "cold")
        self.assertEqual(document["environment_triggers"][0]["path"], "conan.lock")


class DependencyGateTests(unittest.TestCase):
    def test_cache_miss_is_a_successful_cold_path(self) -> None:
        commands = []

        def runner(command):
            commands.append(tuple(command))
            return CommandResult(0, "installed", "")

        conclusion = run_dependency_gate(
            GateRequest("rosbridge", CacheState.MISS),
            runner=runner,
            sleep=lambda _seconds: None,
        )

        self.assertTrue(conclusion.success)
        self.assertEqual(conclusion.dependency_path, DependencyPath.COLD)
        self.assertEqual(conclusion.attempts, 1)
        self.assertEqual(conclusion.failure_class, FailureClass.NONE)
        self.assertIn("Cold", conclusion.diagnostic)
        self.assertEqual(len(commands), 1)

    def test_connectivity_and_download_timeout_retry_only_once(self) -> None:
        for failure in (
            "ssh: connect to host tunnel timed out",
            "package download read timed out",
        ):
            with self.subTest(failure=failure):
                attempts = iter(
                    [
                        CommandResult(1, "", failure),
                        CommandResult(1, "", failure),
                    ]
                )
                sleeps = []
                conclusion = run_dependency_gate(
                    GateRequest("rosbridge", CacheState.HIT),
                    runner=lambda _command: next(attempts),
                    sleep=sleeps.append,
                )

                self.assertFalse(conclusion.success)
                self.assertEqual(conclusion.attempts, 2)
                self.assertEqual(conclusion.failure_class, FailureClass.CONNECTIVITY)
                self.assertEqual(sleeps, [1.0])

    def test_process_timeout_is_bounded_and_retried_only_once(self) -> None:
        call_count = 0

        def runner(command):
            nonlocal call_count
            call_count += 1
            raise subprocess.TimeoutExpired(command, 420)

        conclusion = run_dependency_gate(
            GateRequest("rosbridge", CacheState.HIT),
            runner=runner,
            sleep=lambda _seconds: None,
        )

        self.assertEqual(call_count, 2)
        self.assertEqual(conclusion.attempts, 2)
        self.assertEqual(conclusion.failure_class, FailureClass.CONNECTIVITY)

    def test_deterministic_dependency_failures_do_not_retry(self) -> None:
        cases = {
            "Host key verification failed": FailureClass.HOST_OR_AUTH,
            "HTTP 401 unauthorized": FailureClass.HOST_OR_AUTH,
            "Missing binary: grpc/1.82.0": FailureClass.ARM64_PACKAGE_PREPARATION,
            "ERROR: lockfile not found": FailureClass.CONFIGURATION,
        }

        for output, expected in cases.items():
            with self.subTest(output=output):
                call_count = 0

                def runner(_command):
                    nonlocal call_count
                    call_count += 1
                    return CommandResult(1, "", output)

                conclusion = run_dependency_gate(
                    GateRequest("rosbridge", CacheState.HIT),
                    runner=runner,
                    sleep=lambda _seconds: None,
                )

                self.assertFalse(conclusion.success)
                self.assertEqual(conclusion.failure_class, expected)
                self.assertEqual(conclusion.attempts, 1)
                self.assertEqual(call_count, 1)

    def test_missing_exact_package_is_actionable(self) -> None:
        conclusion = run_dependency_gate(
            GateRequest("required-remote", CacheState.HIT),
            runner=lambda _command: CommandResult(
                1,
                "",
                "Missing binary: grpc/1.82.0",
            ),
            sleep=lambda _seconds: None,
        )

        self.assertIn("ARM64 dependency preparation required", conclusion.diagnostic)
        self.assertIn("required-remote", conclusion.diagnostic)

    def test_cache_service_failure_can_only_fall_back_to_strict_server(self) -> None:
        conclusion = run_dependency_gate(
            GateRequest("rosbridge", CacheState.RESTORE_FAILURE),
            runner=lambda _command: CommandResult(0, "installed", ""),
            sleep=lambda _seconds: None,
        )

        self.assertTrue(conclusion.success)
        self.assertEqual(
            conclusion.dependency_path,
            DependencyPath.STRICT_SERVER_FALLBACK,
        )
        self.assertEqual(conclusion.observed_failures, (FailureClass.CACHE_SERVICE,))
        self.assertIn("strict Server fallback", conclusion.diagnostic)

    def test_diagnostic_is_redacted_and_bounded(self) -> None:
        secret = "super-secret-password"
        known_hosts = "server ssh-ed25519 AAAA-secret\nbackup ssh-ed25519 BBBB-secret"
        output = (
            f"authentication failed password={secret} "
            "https://ci-reader:also-secret@example.invalid "
            f"known hosts: {known_hosts} "
            + ("x" * 5000)
        )
        conclusion = run_dependency_gate(
            GateRequest("rosbridge", CacheState.HIT),
            runner=lambda _command: CommandResult(1, "", output),
            sleep=lambda _seconds: None,
            secrets=(secret, "also-secret", known_hosts),
        )

        self.assertEqual(conclusion.failure_class, FailureClass.HOST_OR_AUTH)
        self.assertNotIn(secret, conclusion.diagnostic)
        self.assertNotIn("also-secret", conclusion.diagnostic)
        self.assertNotIn("AAAA-secret", conclusion.diagnostic)
        self.assertNotIn("BBBB-secret", conclusion.diagnostic)
        self.assertLessEqual(len(conclusion.diagnostic), 1200)

    def test_cache_and_project_failures_have_distinct_terminal_classes(self) -> None:
        cache = classify_terminal_failure("restore-dependency-cache", "service unavailable")
        build = classify_terminal_failure("build", "compiler error")
        lint = classify_terminal_failure("lint", "lint error")
        test = classify_terminal_failure("test", "test error")

        self.assertEqual(cache.failure_class, FailureClass.CACHE_SERVICE)
        for conclusion in (build, lint, test):
            self.assertEqual(conclusion.failure_class, FailureClass.PROJECT)
            self.assertFalse(conclusion.retryable)

    def test_project_failure_diagnostic_redacts_secrets(self) -> None:
        conclusion = classify_terminal_failure(
            "build",
            "compiler received token=do-not-log",
            secrets=("do-not-log",),
        )

        self.assertNotIn("do-not-log", conclusion.diagnostic)
        self.assertIn("token=***", conclusion.diagnostic)


if __name__ == "__main__":
    unittest.main()
