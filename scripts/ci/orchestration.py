"""Shared, testable policy boundary for ARM64 CI execution.

This module is intentionally independent from GitHub Actions wiring.  It turns
trusted event inputs into an explainable plan and provides the strict Conan
dependency gate that future workflows can invoke without enabling source builds.
"""

from __future__ import annotations

import json
import re
import subprocess
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Iterable, Sequence


MAX_DIAGNOSTIC_LENGTH = 1200
_REMOTE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class EventType(str, Enum):
    """Events understood by the shared execution policy."""

    PULL_REQUEST = "pull-request"
    MAIN_PUSH = "main-push"


class CacheState(str, Enum):
    """Observable result of the dependency-cache restore step."""

    HIT = "hit"
    MISS = "miss"
    RESTORE_FAILURE = "restore-failure"


class ExecutionClass(str, Enum):
    """Top-level CI delivery paths."""

    SOURCE_PULL_REQUEST = "source-pull-request"
    ENVIRONMENT_PULL_REQUEST = "environment-pull-request"
    POST_MERGE_IMAGE_UPDATE = "post-merge-image-update"
    NO_ACTION = "no-action"


class EnvironmentCategory(str, Enum):
    """Specification-owned reasons for environment validation."""

    DOCKER_ENVIRONMENT = "docker-environment"
    CONAN_DEPENDENCIES = "conan-dependencies"
    ROS_CMAKE_DEPENDENCIES = "ros-cmake-dependencies"
    PROFILE_FINGERPRINT = "profile-fingerprint"
    CI_BEHAVIOR = "ci-behavior"
    AMBIGUOUS = "ambiguous"


class DependencyPath(str, Enum):
    """How dependency payloads are prepared without changing authority."""

    WARM = "warm"
    COLD = "cold"
    STRICT_SERVER_FALLBACK = "strict-server-fallback"


class FailureClass(str, Enum):
    """Stable terminal classes exposed by CI orchestration."""

    NONE = "none"
    CONNECTIVITY = "tunnel-connectivity"
    HOST_OR_AUTH = "host-auth"
    ARM64_PACKAGE_PREPARATION = "arm64-package-preparation"
    CACHE_SERVICE = "cache-service"
    PROJECT = "project"
    CONFIGURATION = "configuration"


@dataclass(frozen=True)
class ChangeTrigger:
    """An input that conservatively requires environment validation."""

    path: str
    category: EnvironmentCategory
    reason: str
    image_input: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "category": self.category.value,
            "reason": self.reason,
            "image_input": self.image_input,
        }


@dataclass(frozen=True)
class PlanPhase:
    """One ordered phase; multiple steps in a phase may run concurrently."""

    name: str
    steps: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {"name": self.name, "steps": list(self.steps)}


@dataclass(frozen=True)
class ExecutionPlan:
    """Complete externally observable plan for one CI event."""

    execution_class: ExecutionClass
    environment_triggers: tuple[ChangeTrigger, ...]
    dependency_path: DependencyPath
    phases: tuple[PlanPhase, ...]
    publish_image: bool
    explanation: str

    @property
    def phase_steps(self) -> tuple[tuple[str, ...], ...]:
        return tuple(phase.steps for phase in self.phases)

    def to_dict(self) -> dict[str, object]:
        return {
            "execution_class": self.execution_class.value,
            "environment_triggers": [trigger.to_dict() for trigger in self.environment_triggers],
            "dependency_path": self.dependency_path.value,
            "phases": [phase.to_dict() for phase in self.phases],
            "publish_image": self.publish_image,
            "explanation": self.explanation,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)


def _normalize_changed_files(changed_files: Iterable[str]) -> tuple[str, ...]:
    normalized = {path.strip().replace("\\", "/") for path in changed_files if path.strip()}
    return tuple(sorted(normalized))


def _environment_trigger(path: str) -> ChangeTrigger | None:
    filename = path.rsplit("/", 1)[-1]
    if path == "Dockerfile" or path.startswith("docker/"):
        return ChangeTrigger(
            path,
            EnvironmentCategory.DOCKER_ENVIRONMENT,
            "shared Docker toolchain or entrypoint changed",
            image_input=True,
        )
    if path in {"docker-compose.yaml", "docker-compose.yml"}:
        return ChangeTrigger(
            path,
            EnvironmentCategory.DOCKER_ENVIRONMENT,
            "ROS 2 service environment changed",
        )
    if filename in {"conanfile.txt", "conanfile.py", "conan.lock"}:
        return ChangeTrigger(
            path,
            EnvironmentCategory.CONAN_DEPENDENCIES,
            "Conan declaration or locked graph changed",
        )
    if (
        filename in {"package.xml", "CMakeLists.txt"}
        or path.endswith(".cmake")
    ):
        return ChangeTrigger(
            path,
            EnvironmentCategory.ROS_CMAKE_DEPENDENCIES,
            "ROS or CMake dependency declaration changed",
        )
    if (
        path.startswith("ci/profiles/")
        or path.startswith("profiles/")
        or path.startswith(".conan/")
        or "fingerprint" in path.lower()
    ):
        return ChangeTrigger(
            path,
            EnvironmentCategory.PROFILE_FINGERPRINT,
            "Conan profile or compatibility fingerprint policy changed",
        )
    if (
        path.startswith(".github/workflows/")
        or path.startswith(".github/actions/")
        or path.startswith("scripts/ci/")
        or path.startswith("scripts/utils/")
        or path in {
            "rb",
            "scripts/cli.py",
            "scripts/utils/workspace.py",
            "scripts/requirements.txt",
            ".clang-format",
            ".clang-tidy",
        }
    ):
        return ChangeTrigger(
            path,
            EnvironmentCategory.CI_BEHAVIOR,
            "CI policy or required-check behavior changed",
        )
    if (
        path.startswith("src/")
        or path.startswith("scripts/")
        or path.startswith("docs/")
        or path.endswith(".md")
        or path in {"LICENSE", ".gitignore"}
    ):
        return None
    return ChangeTrigger(
        path,
        EnvironmentCategory.AMBIGUOUS,
        "input is not covered by a known source-only rule",
    )


def _dependency_path(cache_state: CacheState) -> DependencyPath:
    if cache_state == CacheState.HIT:
        return DependencyPath.WARM
    if cache_state == CacheState.MISS:
        return DependencyPath.COLD
    return DependencyPath.STRICT_SERVER_FALLBACK


def _dependency_phase(cache_state: CacheState) -> PlanPhase:
    if cache_state == CacheState.RESTORE_FAILURE:
        first_step = "record-cache-service-failure"
    else:
        first_step = "restore-dependency-cache"
    return PlanPhase(
        "dependencies",
        (
            first_step,
            "verify-required-conan-remote",
            "install-locked-arm64-dependencies",
        ),
    )


def create_execution_plan(
    event: EventType,
    changed_files: Iterable[str],
    cache_state: CacheState,
) -> ExecutionPlan:
    """Create the complete explainable plan for event and changed-input evidence."""
    paths = _normalize_changed_files(changed_files)
    triggers = tuple(
        trigger
        for path in paths
        for trigger in [_environment_trigger(path)]
        if trigger is not None
    )
    dependency_path = _dependency_path(cache_state)

    if event == EventType.MAIN_PUSH:
        image_inputs = tuple(trigger.path for trigger in triggers if trigger.image_input)
        if not image_inputs:
            changed = ", ".join(trigger.path for trigger in triggers) or "source-only inputs"
            return ExecutionPlan(
                ExecutionClass.NO_ACTION,
                triggers,
                dependency_path,
                (),
                False,
                f"Main push has no CI image input; publication is skipped ({changed}).",
            )
        phases = (
            PlanPhase("environment", ("build-candidate-image",)),
            _dependency_phase(cache_state),
            PlanPhase("build", ("build",)),
            PlanPhase("checks", ("lint", "test")),
            PlanPhase("cache", ("refresh-trusted-cache",)),
            PlanPhase("publication", ("publish-ci-image",)),
        )
        return ExecutionPlan(
            ExecutionClass.POST_MERGE_IMAGE_UPDATE,
            triggers,
            dependency_path,
            phases,
            True,
            "Post-merge CI image update was triggered by: " + ", ".join(image_inputs),
        )

    if triggers:
        phases = (
            PlanPhase("environment", ("build-candidate-image",)),
            _dependency_phase(cache_state),
            PlanPhase("build", ("build",)),
            PlanPhase("checks", ("lint", "test")),
        )
        return ExecutionPlan(
            ExecutionClass.ENVIRONMENT_PULL_REQUEST,
            triggers,
            dependency_path,
            phases,
            False,
            "Environment validation was triggered by: "
            + ", ".join(trigger.path for trigger in triggers),
        )

    phases = (
        PlanPhase("environment", ("reuse-ci-image",)),
        _dependency_phase(cache_state),
        PlanPhase("build", ("build",)),
        PlanPhase("checks", ("lint", "test")),
    )
    return ExecutionPlan(
        ExecutionClass.SOURCE_PULL_REQUEST,
        (),
        dependency_path,
        phases,
        False,
        "All changed inputs are covered by source-only rules; reuse the published CI image.",
    )


@dataclass(frozen=True)
class GateRequest:
    """Inputs needed to construct one strict Conan dependency Gate."""

    remote_name: str
    cache_state: CacheState
    lockfile: str = "conan.lock"
    host_profile: str = "default"
    build_profile: str = "default"
    output_folder: str = "build"
    download_cache: str | None = None
    attempt_timeout_seconds: int = 420


@dataclass(frozen=True)
class CommandResult:
    """Captured result from one strict Conan attempt."""

    returncode: int
    stdout: str = ""
    stderr: str = ""


@dataclass(frozen=True)
class TerminalConclusion:
    """Stable failure policy for a failed orchestration stage."""

    failure_class: FailureClass
    retryable: bool
    diagnostic: str


@dataclass(frozen=True)
class GateConclusion:
    """Bounded and redacted result of strict dependency preparation."""

    success: bool
    dependency_path: DependencyPath
    attempts: int
    failure_class: FailureClass
    diagnostic: str
    command: tuple[str, ...]
    observed_failures: tuple[FailureClass, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "success": self.success,
            "dependency_path": self.dependency_path.value,
            "attempts": self.attempts,
            "failure_class": self.failure_class.value,
            "diagnostic": self.diagnostic,
            "command": list(self.command),
            "observed_failures": [failure.value for failure in self.observed_failures],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)


def build_strict_conan_command(request: GateRequest) -> list[str]:
    """Build a locked ARM64 install command that can never compile a package."""
    remote_name = request.remote_name.strip()
    if not _REMOTE_NAME.fullmatch(remote_name):
        raise ValueError("Conan remote name is required and may contain only safe name characters")
    if not request.lockfile.strip():
        raise ValueError("Conan lockfile path is required")
    if not request.host_profile.strip() or not request.build_profile.strip():
        raise ValueError("Conan host and build profiles are required")
    if not request.output_folder.strip():
        raise ValueError("Conan output folder is required")
    if not 1 <= request.attempt_timeout_seconds <= 420:
        raise ValueError("Conan attempt timeout must be between 1 and 420 seconds")

    command = [
        "conan",
        "install",
        ".",
        f"--lockfile={request.lockfile}",
        f"--output-folder={request.output_folder}",
        f"--remote={remote_name}",
        "--build=never",
        f"--profile:host={request.host_profile}",
        f"--profile:build={request.build_profile}",
        "--settings:host=arch=armv8",
        "--settings:build=arch=armv8",
        "--settings:host=build_type=Release",
        "--settings:host=compiler.cppstd=17",
    ]
    if request.download_cache:
        if not Path(request.download_cache).is_absolute():
            raise ValueError("Conan download cache path must be absolute")
        command.extend(
            ["-cc", f"core.download:download_cache={request.download_cache}"]
        )
    return command


_HOST_AUTH_PATTERNS = (
    "host key verification failed",
    "remote host identification has changed",
    "authentication failed",
    "unauthorized",
    "forbidden",
    "invalid credentials",
    "permission denied",
    "http 401",
    "http 403",
)
_PACKAGE_PATTERNS = (
    "missing binary",
    "missing prebuilt package",
    "package binary is missing",
    "cannot find a compatible package",
    "exact package not found",
)
_CONFIGURATION_PATTERNS = (
    "lockfile not found",
    "profile not found",
    "invalid setting",
    "invalid configuration",
    "remote not found",
    "unknown remote",
)
_CONNECTIVITY_PATTERNS = (
    "connect to host",
    "connection refused",
    "connection reset",
    "connection error",
    "unable to connect",
    "failed to establish a new connection",
    "network is unreachable",
    "name or service not known",
    "temporary failure in name resolution",
    "server unavailable",
    "service unavailable",
    "read timed out",
    "download timed out",
    "download timeout",
    "connection timed out",
    "operation timed out",
    "tunnel timed out",
    "timeouterror",
    "http 502",
    "http 503",
    "http 504",
)


def _redact(text: str, secrets: Iterable[str]) -> str:
    secret_values = tuple(secret for secret in secrets if secret)
    redacted = text
    for secret in sorted(secret_values, key=len, reverse=True):
        redacted = redacted.replace(secret, "***")
    redacted = redacted.replace("\r", " ").replace("\n", " ")
    normalized_secrets = (
        secret.replace("\r", " ").replace("\n", " ") for secret in secret_values
    )
    for secret in sorted(normalized_secrets, key=len, reverse=True):
        redacted = redacted.replace(secret, "***")
    redacted = re.sub(
        r"(://)[^/\s:@]+:[^/@\s]+@",
        r"\1***:***@",
        redacted,
    )
    redacted = re.sub(
        r"(?i)\b(password|passwd|token|authorization|secret)\s*[:=]\s*"
        r"(?:bearer\s+|basic\s+)?[^\s,;]+",
        r"\1=***",
        redacted,
    )
    redacted = re.sub(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9+/=_.-]+", r"\1 ***", redacted)
    return " ".join(redacted.split())


def _bounded(text: str) -> str:
    if len(text) <= MAX_DIAGNOSTIC_LENGTH:
        return text
    suffix = "... [diagnostic truncated]"
    return text[: MAX_DIAGNOSTIC_LENGTH - len(suffix)] + suffix


def _safe_detail(text: str, secrets: Iterable[str]) -> str:
    return _bounded(_redact(text, secrets))


def _classify_dependency_output(output: str) -> FailureClass:
    lowered = output.lower()
    if any(pattern in lowered for pattern in _HOST_AUTH_PATTERNS):
        return FailureClass.HOST_OR_AUTH
    if any(pattern in lowered for pattern in _PACKAGE_PATTERNS):
        return FailureClass.ARM64_PACKAGE_PREPARATION
    if any(pattern in lowered for pattern in _CONFIGURATION_PATTERNS):
        return FailureClass.CONFIGURATION
    if any(pattern in lowered for pattern in _CONNECTIVITY_PATTERNS):
        return FailureClass.CONNECTIVITY
    return FailureClass.CONFIGURATION


def classify_terminal_failure(
    stage: str,
    output: str,
    *,
    secrets: Iterable[str] = (),
) -> TerminalConclusion:
    """Classify a failed stage without exposing raw or unbounded diagnostics."""
    normalized_stage = stage.strip().lower()
    detail = _safe_detail(output, secrets)
    if normalized_stage == "restore-dependency-cache":
        failure_class = FailureClass.CACHE_SERVICE
        message = "Dependency cache service failed; continue only through the strict Server path."
        retryable = False
    elif normalized_stage in {"build", "lint", "test"}:
        failure_class = FailureClass.PROJECT
        message = f"Project {normalized_stage} failed; automatic retry is disabled."
        retryable = False
    else:
        failure_class = _classify_dependency_output(output)
        messages = {
            FailureClass.CONNECTIVITY: "Conan tunnel/connectivity failed.",
            FailureClass.HOST_OR_AUTH: "Conan host identity or authentication failed.",
            FailureClass.ARM64_PACKAGE_PREPARATION: (
                "ARM64 dependency preparation required: an exact locked package is unavailable."
            ),
            FailureClass.CONFIGURATION: "Strict Conan configuration failed.",
        }
        message = messages[failure_class]
        retryable = failure_class == FailureClass.CONNECTIVITY
    if detail:
        message += f" Detail: {detail}"
    return TerminalConclusion(failure_class, retryable, _bounded(message))


def _run_command(command: Sequence[str], timeout_seconds: int) -> CommandResult:
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def _gate_failure_diagnostic(
    failure_class: FailureClass,
    output: str,
    request: GateRequest,
    attempts: int,
    secrets: Iterable[str],
) -> str:
    detail = _safe_detail(output, secrets)
    if failure_class == FailureClass.CONNECTIVITY:
        message = (
            f"Conan tunnel/connectivity failed after {attempts} attempt(s); "
            "verify the restricted tunnel and Server availability."
        )
    elif failure_class == FailureClass.HOST_OR_AUTH:
        message = (
            "Conan host identity or authentication failed; verify known-host material and "
            "the read-only identity."
        )
    elif failure_class == FailureClass.ARM64_PACKAGE_PREPARATION:
        message = (
            "ARM64 dependency preparation required: the exact package selected by conan.lock "
            f"is unavailable on remote '{request.remote_name}'."
        )
    else:
        message = (
            "Strict Conan configuration failed; verify the required remote, lockfile, and "
            "ARM64 profiles."
        )
    if detail:
        message += f" Detail: {detail}"
    return _bounded(message)


def run_dependency_gate(
    request: GateRequest,
    *,
    runner: Callable[[Sequence[str]], CommandResult] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    secrets: Iterable[str] = (),
) -> GateConclusion:
    """Run strict Conan preparation with one retry only for transient network failures."""
    command = tuple(build_strict_conan_command(request))
    execute = runner or (
        lambda requested_command: _run_command(
            requested_command,
            request.attempt_timeout_seconds,
        )
    )
    dependency_path = _dependency_path(request.cache_state)
    observed_failures = (
        (FailureClass.CACHE_SERVICE,)
        if request.cache_state == CacheState.RESTORE_FAILURE
        else ()
    )

    for attempt in range(1, 3):
        try:
            result = execute(command)
        except subprocess.TimeoutExpired as error:
            stdout = (
                error.stdout.decode(errors="replace")
                if isinstance(error.stdout, bytes)
                else error.stdout
            )
            stderr = (
                error.stderr.decode(errors="replace")
                if isinstance(error.stderr, bytes)
                else error.stderr
            )
            result = CommandResult(
                124,
                stdout or "",
                (stderr or "") + "\ndependency download operation timed out",
            )
        except OSError as error:
            result = CommandResult(127, "", f"Conan process configuration failed: {error}")
        if result.returncode == 0:
            messages = {
                DependencyPath.WARM: (
                    "Warm dependency path completed through the required Conan remote."
                ),
                DependencyPath.COLD: (
                    "Cold dependency path completed through the required Conan remote."
                ),
                DependencyPath.STRICT_SERVER_FALLBACK: (
                    "Cache restore service failed; strict Server fallback completed without "
                    "source builds."
                ),
            }
            return GateConclusion(
                True,
                dependency_path,
                attempt,
                FailureClass.NONE,
                messages[dependency_path],
                command,
                observed_failures,
            )

        output = "\n".join(part for part in (result.stderr, result.stdout) if part)
        terminal = classify_terminal_failure(
            "strict-arm64-dependency-gate",
            output,
            secrets=secrets,
        )
        if terminal.retryable and attempt == 1:
            sleep(1.0)
            continue
        return GateConclusion(
            False,
            dependency_path,
            attempt,
            terminal.failure_class,
            _gate_failure_diagnostic(
                terminal.failure_class,
                output,
                request,
                attempt,
                secrets,
            ),
            command,
            observed_failures,
        )

    raise AssertionError("dependency Gate exceeded its two-attempt bound")
