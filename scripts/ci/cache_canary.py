"""Cache identity and evidence policy for the ARM64 Conan canary."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence
from urllib.parse import urlsplit

from scripts.ci.orchestration import (
    CacheState,
    CommandResult,
    DependencyPath,
    GateConclusion,
    GateRequest,
    classify_terminal_failure,
    run_dependency_gate,
)


CACHE_KEY_NAMESPACE = "rosbridge-conan-download"
GIB = 1024**3
REPOSITORY_CACHE_LIMIT_BYTES = 10 * GIB
_GENERATION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_REMOTE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_CI_STAGE = re.compile(r"^FROM\s+base\s+AS\s+ci\s*$", re.IGNORECASE | re.MULTILINE)
_REQUIRED_EVIDENCE_FIELDS = frozenset(
    {
        "architecture",
        "os",
        "ros",
        "compiler",
        "libc",
        "conan",
        "host_profile",
        "build_profile",
        "build_settings",
        "options",
        "shared_base",
    }
)
_FORBIDDEN_CACHE_NAMES = frozenset(
    {
        ".netrc",
        "auth.json",
        "credentials.json",
        "global.conf",
        "id_ed25519",
        "id_rsa",
        "known_hosts",
        "remotes.json",
        "settings.yml",
        "source_credentials.json",
    }
)
_GRAPH_FIELDS = ("ref", "rrev", "package_id", "prev", "context")
_HOST_SETTINGS = {
    "arch": "armv8",
    "build_type": "Release",
    "compiler.cppstd": "17",
}
_BUILD_SETTINGS = {
    "arch": "armv8",
    "build_type": "Release",
    "compiler.cppstd": "17",
}


class RestoreKind(str, Enum):
    """Observable Actions cache restore outcome."""

    EXACT = "exact"
    COMPATIBLE = "compatible"
    MISS = "miss"
    FAILURE = "failure"


class SampleRole(str, Enum):
    """Expected cache state for producer and correctness canary samples."""

    PRODUCER = "producer"
    COLD = "cold"
    WARM = "warm"
    RECOVERY = "recovery"


@dataclass(frozen=True)
class CacheIdentity:
    """Stable identity and restore namespace for one compatible dependency graph."""

    generation: str
    architecture: str
    environment_fingerprint: str
    locked_dependency_hash: str
    key: str
    restore_prefix: str

    def to_dict(self) -> dict[str, str]:
        return {
            "generation": self.generation,
            "architecture": self.architecture,
            "environment_fingerprint": self.environment_fingerprint,
            "locked_dependency_hash": self.locked_dependency_hash,
            "key": self.key,
            "restore_prefix": self.restore_prefix,
        }


@dataclass(frozen=True)
class CacheRestore:
    """Validated cache restore classification passed into the strict Gate."""

    kind: RestoreKind
    cache_state: CacheState
    matched_key: str


@dataclass(frozen=True)
class CacheSnapshot:
    """Credential-safe identity and size of the download-cache payload."""

    digest: str
    bytes: int
    files: int

    def to_dict(self) -> dict[str, object]:
        return {"digest": self.digest, "bytes": self.bytes, "files": self.files}


@dataclass(frozen=True)
class CapacityDecision:
    """Save eligibility and non-blocking cache-capacity observations."""

    save_allowed: bool
    warnings: tuple[str, ...]
    reason: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "save_allowed": self.save_allowed,
            "warnings": list(self.warnings),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class GraphEvidence:
    """Stable exact-package identity emitted by the strict Conan Gate."""

    digest: str
    package_count: int
    source_builds: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "digest": self.digest,
            "package_count": self.package_count,
            "source_builds": list(self.source_builds),
        }


@dataclass(frozen=True)
class CanaryRequest:
    """Inputs for one strict producer or restore-only canary execution."""

    sample_role: SampleRole
    identity: CacheIdentity
    restore: CacheRestore
    cache_dir: Path
    graph_file: Path
    output_folder: Path
    remote_name: str
    restore_seconds: float
    repository_cache_bytes: int
    cache_read_only: bool = False
    recovery_from_generation: str = ""
    recovery_control_key: str = ""
    total_start_unix_ms: int = 0
    lockfile: Path = Path("conan.lock")
    host_profile: str = "default"
    build_profile: str = "default"
    attempt_timeout_seconds: int = 420


@dataclass(frozen=True)
class CanaryEvidence:
    """Credential-free correctness, performance, and capacity evidence."""

    sample_role: SampleRole
    identity: CacheIdentity
    restore: CacheRestore
    cache_before: CacheSnapshot
    cache_after: CacheSnapshot
    graph: GraphEvidence
    capacity: CapacityDecision
    attempts: int
    restore_seconds: float
    conan_seconds: float
    build_seconds: float
    total_seconds: float
    recovery_from_generation: str = ""
    recovery_control_key: str = ""
    warm_payload_enforcement: str = ""
    server_verified: bool = True

    @property
    def payload_changed(self) -> bool:
        return self.cache_before != self.cache_after

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "sample_role": self.sample_role.value,
            "cache_identity": self.identity.to_dict(),
            "restore_kind": self.restore.kind.value,
            "matched_key": self.restore.matched_key,
            "dependency_path": self.restore.cache_state.value,
            "server_verified": self.server_verified,
            "attempts": self.attempts,
            "graph_digest": self.graph.digest,
            "package_count": self.graph.package_count,
            "source_builds": list(self.graph.source_builds),
            "cache_before": self.cache_before.to_dict(),
            "cache_after": self.cache_after.to_dict(),
            "payload_changed": self.payload_changed,
            "payload_downloads": 0 if self.warm_payload_enforcement else None,
            "warm_payload_enforcement": self.warm_payload_enforcement,
            "recovery_from_generation": self.recovery_from_generation,
            "recovery_control_key": self.recovery_control_key,
            "capacity": self.capacity.to_dict(),
            "timings_seconds": {
                "restore": round(self.restore_seconds, 3),
                "conan": round(self.conan_seconds, 3),
                "build": round(self.build_seconds, 3),
                "total": round(self.total_seconds, 3),
            },
        }


def _normalize_architecture(value: object) -> str:
    architecture = str(value).strip().lower()
    aliases = {
        "aarch64": "arm64",
        "arm64": "arm64",
        "armv8": "arm64",
        "amd64": "x86_64",
        "x86_64": "x86_64",
    }
    try:
        return aliases[architecture]
    except KeyError as error:
        raise ValueError("unsupported cache architecture") from error


def _normalize_json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key).strip(): _normalize_json_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_normalize_json_value(item) for item in value]
    if isinstance(value, str):
        return value.strip()
    if value is None or isinstance(value, (bool, int, float)):
        return value
    raise ValueError("environment evidence contains an unsupported value")


def _canonical_json(payload: object) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def shared_base_digest(dockerfile: str, entrypoint: bytes) -> str:
    """Hash shared Docker inputs while excluding the simulator-only dev stage."""
    normalized = dockerfile.replace("\r\n", "\n")
    marker = _CI_STAGE.search(normalized)
    if marker is None:
        raise ValueError("Dockerfile does not define the shared ci stage boundary")
    shared_base = normalized[: marker.start()].rstrip() + "\n"
    return _sha256(
        b"docker-base\0"
        + shared_base.encode("utf-8")
        + b"\0entrypoint\0"
        + entrypoint
    )


def _capture(command: Sequence[str]) -> str:
    completed = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _parse_os_release(path: Path) -> dict[str, str]:
    try:
        values = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line or line.lstrip().startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", maxsplit=1)
            values[name] = value.strip().strip('"').strip("'")
        return {"id": values["ID"], "version_id": values["VERSION_ID"]}
    except (OSError, UnicodeError, KeyError) as error:
        raise RuntimeError("OS compatibility evidence is unavailable") from error


def _declared_options(path: Path) -> dict[str, str]:
    try:
        section = ""
        options = {}
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.split("#", maxsplit=1)[0].strip()
            if not line:
                continue
            if line.startswith("[") and line.endswith("]"):
                section = line[1:-1].strip().lower()
                continue
            if section == "options" and "=" in line:
                name, value = line.split("=", maxsplit=1)
                options[name.strip()] = value.strip()
        return dict(sorted(options.items()))
    except (OSError, UnicodeError) as error:
        raise RuntimeError("Conan option evidence is unavailable") from error


def _settings_arguments(prefix: str, settings: Mapping[str, str]) -> list[str]:
    return [
        argument
        for name, value in settings.items()
        for argument in (f"--settings:{prefix}", f"{name}={value}")
    ]


def collect_environment_evidence(
    repository: Path,
    *,
    host_profile: str = "default",
    build_profile: str = "default",
    environ: Mapping[str, str] | None = None,
    os_release: Path | None = None,
    runner: Callable[[Sequence[str]], str] = _capture,
) -> dict[str, object]:
    """Collect effective compatibility evidence inside the active dev/CI container."""
    values = os.environ if environ is None else environ
    ros_distro = values.get("ROS_DISTRO", "").strip()
    if not ros_distro:
        raise RuntimeError("ROS compatibility evidence is unavailable")
    if not host_profile.strip() or not build_profile.strip():
        raise ValueError("effective Conan host and build profiles are required")

    profile_command = [
        "conan",
        "profile",
        "show",
        f"--profile:host={host_profile}",
        f"--profile:build={build_profile}",
        *_settings_arguments("host", _HOST_SETTINGS),
        *_settings_arguments("build", _BUILD_SETTINGS),
        "--format=json",
    ]
    try:
        profile_payload = json.loads(runner(profile_command))
        host_evidence = profile_payload.get("host_profile", profile_payload.get("host"))
        build_evidence = profile_payload.get("build_profile", profile_payload.get("build"))
        if not isinstance(host_evidence, Mapping) or not isinstance(build_evidence, Mapping):
            raise TypeError
    except (AttributeError, TypeError, json.JSONDecodeError, subprocess.SubprocessError) as error:
        raise RuntimeError("effective Conan profile evidence is unavailable") from error

    compiler_version = runner(["g++", "-dumpfullversion", "-dumpversion"]).strip()
    compiler_target = runner(["g++", "-dumpmachine"]).strip()
    libc_parts = runner(["getconf", "GNU_LIBC_VERSION"]).strip().split(maxsplit=1)
    conan_parts = runner(["conan", "--version"]).strip().split()
    if not compiler_version or not compiler_target or len(libc_parts) != 2 or not conan_parts:
        raise RuntimeError("compiler or package-manager compatibility evidence is unavailable")

    dockerfile = repository / "docker" / "Dockerfile"
    entrypoint = repository / "docker" / "entrypoint.sh"
    try:
        shared_digest = shared_base_digest(
            dockerfile.read_text(encoding="utf-8"),
            entrypoint.read_bytes(),
        )
    except (OSError, UnicodeError) as error:
        raise RuntimeError("shared Docker compatibility evidence is unavailable") from error

    return {
        "architecture": _normalize_architecture(runner(["uname", "-m"])),
        "os": _parse_os_release(os_release or Path("/etc/os-release")),
        "ros": {"distro": ros_distro},
        "compiler": {
            "id": "gcc",
            "target": compiler_target,
            "version": compiler_version,
        },
        "libc": {"id": libc_parts[0], "version": libc_parts[1]},
        "conan": {"version": conan_parts[-1]},
        "host_profile": _normalize_json_value(host_evidence),
        "build_profile": _normalize_json_value(build_evidence),
        "build_settings": {"host": dict(_HOST_SETTINGS), "build": dict(_BUILD_SETTINGS)},
        "options": _declared_options(repository / "conanfile.txt"),
        "shared_base": {"digest": shared_digest},
    }


def _run_control_command(command: Sequence[str]) -> CommandResult:
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return CommandResult(completed.returncode, completed.stdout, completed.stderr)
    except subprocess.TimeoutExpired as error:
        stdout = error.stdout.decode(errors="replace") if isinstance(error.stdout, bytes) else error.stdout
        stderr = error.stderr.decode(errors="replace") if isinstance(error.stderr, bytes) else error.stderr
        return CommandResult(124, stdout or "", (stderr or "") + "\nConan control operation timed out")
    except OSError as error:
        return CommandResult(127, "", f"Conan control process failed: {error}")


def configure_required_remote(
    remote_name: str,
    remote_url: str,
    *,
    runner: Callable[[Sequence[str]], CommandResult] = _run_control_command,
    secrets: Iterable[str] = (),
) -> None:
    """Configure and authenticate the loopback-only endpoint of the restricted tunnel."""
    if not _REMOTE_NAME.fullmatch(remote_name.strip()):
        raise ValueError("required Conan remote name contains unsupported characters")
    endpoint = urlsplit(remote_url)
    if (
        endpoint.scheme != "http"
        or endpoint.hostname not in {"127.0.0.1", "::1", "localhost"}
        or endpoint.username is not None
        or endpoint.password is not None
        or endpoint.port is None
    ):
        raise ValueError("required Conan remote must use a credential-free loopback tunnel URL")
    commands = (
        ("conan", "profile", "detect", "--force"),
        ("conan", "remote", "add", remote_name, remote_url, "--force"),
        ("conan", "remote", "auth", remote_name, "--force", "--strict"),
    )
    secret_values = tuple(secrets)
    for command in commands:
        result = runner(command)
        if result.returncode == 0:
            continue
        output = "\n".join(part for part in (result.stderr, result.stdout) if part)
        terminal = classify_terminal_failure(
            "strict-arm64-dependency-gate",
            output,
            secrets=secret_values,
        )
        raise RuntimeError(terminal.diagnostic)


def _locked_dependency_hash(lockfile: Path, dependency_files: Sequence[Path]) -> str:
    if not dependency_files:
        raise ValueError("at least one dependency declaration is required")
    inputs = [("lockfile", lockfile), *(('dependency', path) for path in dependency_files)]
    logical_names = [f"{kind}:{path.name}" for kind, path in inputs]
    if len(logical_names) != len(set(logical_names)):
        raise ValueError("dependency identity contains duplicate file names")

    digest = hashlib.sha256()
    for logical_name, (_, path) in sorted(zip(logical_names, inputs), key=lambda item: item[0]):
        if not path.is_file():
            raise ValueError("dependency identity input is not a regular file")
        digest.update(logical_name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def build_cache_identity(
    *,
    generation: str,
    evidence: Mapping[str, object],
    lockfile: Path,
    dependency_files: Sequence[Path],
) -> CacheIdentity:
    """Build the normalized cache identity shared by local dev and GitHub CI."""
    generation = generation.strip()
    if not _GENERATION.fullmatch(generation):
        raise ValueError("cache generation contains unsupported characters")
    if set(evidence) != _REQUIRED_EVIDENCE_FIELDS:
        raise ValueError("environment evidence fields do not match the compatibility schema")

    normalized = _normalize_json_value(evidence)
    assert isinstance(normalized, dict)
    architecture = _normalize_architecture(normalized["architecture"])
    normalized["architecture"] = architecture
    environment_fingerprint = _sha256(_canonical_json(normalized))
    locked_hash = _locked_dependency_hash(lockfile, dependency_files)
    restore_prefix = (
        f"{CACHE_KEY_NAMESPACE}-{generation}-{architecture}-{environment_fingerprint}-"
    )
    return CacheIdentity(
        generation=generation,
        architecture=architecture,
        environment_fingerprint=environment_fingerprint,
        locked_dependency_hash=locked_hash,
        key=restore_prefix + locked_hash,
        restore_prefix=restore_prefix,
    )


def classify_cache_restore(
    identity: CacheIdentity,
    *,
    matched_key: str | None,
    restore_failed: bool = False,
) -> CacheRestore:
    """Validate exact/prefix restoration before cache contents reach the Gate."""
    matched_key = (matched_key or "").strip()
    if restore_failed:
        if matched_key:
            raise ValueError("failed cache restoration cannot report a matched key")
        return CacheRestore(RestoreKind.FAILURE, CacheState.RESTORE_FAILURE, "")
    if not matched_key:
        return CacheRestore(RestoreKind.MISS, CacheState.MISS, "")
    if matched_key == identity.key:
        return CacheRestore(RestoreKind.EXACT, CacheState.HIT, matched_key)
    if matched_key.startswith(identity.restore_prefix):
        return CacheRestore(RestoreKind.COMPATIBLE, CacheState.HIT, matched_key)
    raise ValueError("restored cache key is outside the compatible restore prefix")


def _secret_bytes(secrets: Iterable[str]) -> tuple[bytes, ...]:
    values = {
        secret.encode("utf-8")
        for secret in secrets
        if secret and len(secret.encode("utf-8")) >= 4
    }
    return tuple(sorted(values, key=len, reverse=True))


def _hash_and_scan_file(path: Path, secrets: tuple[bytes, ...]) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    overlap = max((len(secret) for secret in secrets), default=1) - 1
    carry = b""
    try:
        with path.open("rb") as source:
            while True:
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                digest.update(chunk)
                searchable = carry + chunk
                if any(secret in searchable for secret in secrets):
                    raise RuntimeError("download cache contains secret material")
                carry = searchable[-overlap:] if overlap else b""
    except RuntimeError:
        raise
    except OSError as error:
        raise RuntimeError("download cache could not be inspected safely") from error
    return digest.hexdigest(), size


def inspect_download_cache(
    cache_dir: Path,
    *,
    secrets: Iterable[str] = (),
) -> CacheSnapshot:
    """Fail closed on credential-bearing or non-regular download-cache contents."""
    if not cache_dir.is_dir() or cache_dir.is_symlink():
        raise RuntimeError("download cache is not a safe directory")
    secret_values = _secret_bytes(secrets)
    files: list[Path] = []
    try:
        for root, directories, names in os.walk(cache_dir, followlinks=False):
            root_path = Path(root)
            for directory in directories:
                if (root_path / directory).is_symlink():
                    raise RuntimeError("download cache contains a symlink")
            for name in names:
                path = root_path / name
                if path.is_symlink():
                    raise RuntimeError("download cache contains a symlink")
                if name.lower() in _FORBIDDEN_CACHE_NAMES:
                    raise RuntimeError("download cache contains credential-bearing configuration")
                if not path.is_file():
                    raise RuntimeError("download cache contains a non-regular file")
                files.append(path)
    except RuntimeError:
        raise
    except OSError as error:
        raise RuntimeError("download cache could not be inspected safely") from error

    snapshot = hashlib.sha256()
    total_bytes = 0
    for path in sorted(files, key=lambda candidate: candidate.relative_to(cache_dir).as_posix()):
        file_digest, file_bytes = _hash_and_scan_file(path, secret_values)
        relative = path.relative_to(cache_dir).as_posix()
        snapshot.update(relative.encode("utf-8"))
        snapshot.update(b"\0")
        snapshot.update(str(file_bytes).encode("ascii"))
        snapshot.update(b"\0")
        snapshot.update(file_digest.encode("ascii"))
        snapshot.update(b"\0")
        total_bytes += file_bytes
    return CacheSnapshot(snapshot.hexdigest(), total_bytes, len(files))


def evaluate_cache_capacity(
    entry_bytes: int,
    repository_bytes: int,
    *,
    repository_limit_bytes: int = REPOSITORY_CACHE_LIMIT_BYTES,
    pending_save: bool = False,
) -> CapacityDecision:
    """Apply the ticket's entry refusal and repository warning thresholds."""
    if min(entry_bytes, repository_bytes, repository_limit_bytes) < 0:
        raise ValueError("cache capacity values must be nonnegative")
    if repository_limit_bytes == 0:
        raise ValueError("repository cache limit must be positive")

    warnings: list[str] = []
    if entry_bytes > GIB:
        warnings.append("single cache entry exceeds the 1 GiB warning threshold")
    projected_repository_bytes = repository_bytes + (entry_bytes if pending_save else 0)
    if projected_repository_bytes * 5 >= repository_limit_bytes * 4:
        warnings.append("repository cache usage reached the 80% warning threshold")
    if entry_bytes > 2 * GIB:
        return CapacityDecision(
            False,
            tuple(warnings),
            "single cache entry exceeds 2 GiB and must not be saved",
        )
    return CapacityDecision(True, tuple(warnings))


def read_graph_evidence(graph_file: Path) -> GraphEvidence:
    """Reduce Conan graph JSON to exact package identity and reject source builds."""
    try:
        payload = json.loads(graph_file.read_text(encoding="utf-8"))
        nodes = payload["graph"]["nodes"]
        if not isinstance(nodes, Mapping):
            raise TypeError
        packages = []
        source_builds = []
        for node in nodes.values():
            if not isinstance(node, Mapping):
                raise TypeError
            reference = node.get("ref")
            if not reference or reference == "conanfile":
                continue
            package = {field: node.get(field) for field in _GRAPH_FIELDS}
            if any(value is None or str(value).strip() == "" for value in package.values()):
                raise TypeError
            packages.append(package)
            if str(node.get("binary", "")).strip().lower() == "build":
                source_builds.append("detected")
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise RuntimeError("Conan graph evidence is malformed") from error

    if source_builds:
        raise RuntimeError("Conan graph evidence contains a source build")
    packages.sort(
        key=lambda package: tuple(str(package.get(field) or "") for field in _GRAPH_FIELDS)
    )
    digest = _sha256(_canonical_json(packages))
    return GraphEvidence(digest, len(packages))


def _run_build(command: Sequence[str]) -> CommandResult:
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=600,
        )
        return CommandResult(completed.returncode, completed.stdout, completed.stderr)
    except subprocess.TimeoutExpired as error:
        stdout = error.stdout.decode(errors="replace") if isinstance(error.stdout, bytes) else error.stdout
        stderr = error.stderr.decode(errors="replace") if isinstance(error.stderr, bytes) else error.stderr
        return CommandResult(124, stdout or "", (stderr or "") + "\nproject build timed out")
    except OSError as error:
        return CommandResult(127, "", f"project build process failed: {error}")


def _expected_dependency_path(restore: CacheRestore) -> DependencyPath:
    if restore.cache_state == CacheState.HIT:
        return DependencyPath.WARM
    if restore.cache_state == CacheState.MISS:
        return DependencyPath.COLD
    return DependencyPath.STRICT_SERVER_FALLBACK


def run_canary(
    request: CanaryRequest,
    *,
    gate_runner: Callable[[GateRequest, Iterable[str]], GateConclusion] | None = None,
    build_runner: Callable[[Sequence[str]], CommandResult] = _run_build,
    clock: Callable[[], float] = time.monotonic,
    wall_clock_ms: Callable[[], int] = lambda: time.time_ns() // 1_000_000,
    secrets: Iterable[str] = (),
) -> CanaryEvidence:
    """Run the strict Gate and build, returning only credential-free evidence."""
    if request.restore_seconds < 0 or not request.restore_seconds < float("inf"):
        raise ValueError("cache restore timing must be finite and nonnegative")
    if request.repository_cache_bytes < 0:
        raise ValueError("repository cache usage must be nonnegative")
    if request.total_start_unix_ms < 0:
        raise ValueError("total timing start must be nonnegative")
    if not request.cache_dir.is_absolute() or not request.graph_file.is_absolute():
        raise ValueError("canary cache and graph paths must be absolute")
    if not request.output_folder.is_absolute():
        raise ValueError("canary output folder must be absolute")
    expected_restore_kinds = {
        SampleRole.COLD: {RestoreKind.MISS},
        SampleRole.WARM: {RestoreKind.EXACT},
        SampleRole.RECOVERY: {RestoreKind.MISS},
    }
    allowed = expected_restore_kinds.get(request.sample_role)
    if allowed is not None and request.restore.kind not in allowed:
        raise RuntimeError("cache sample role does not match the observed restore identity")
    if request.restore.kind == RestoreKind.EXACT and not request.cache_read_only:
        raise RuntimeError("Warm cache requires a read-only package payload mount")
    recovery_from_generation = request.recovery_from_generation.strip()
    if request.sample_role == SampleRole.RECOVERY and (
        not recovery_from_generation or recovery_from_generation == request.identity.generation
    ):
        raise RuntimeError("Recovery requires a distinct previous cache generation")
    if request.sample_role == SampleRole.RECOVERY:
        expected_control_key = (
            f"{CACHE_KEY_NAMESPACE}-{recovery_from_generation}-"
            f"{request.identity.architecture}-{request.identity.environment_fingerprint}-"
            f"{request.identity.locked_dependency_hash}"
        )
        if request.recovery_control_key.strip() != expected_control_key:
            raise RuntimeError("Recovery requires an exact populated previous-generation control")

    secret_values = tuple(secrets)
    before = inspect_download_cache(request.cache_dir, secrets=secret_values)
    gate_request = GateRequest(
        remote_name=request.remote_name,
        cache_state=request.restore.cache_state,
        lockfile=str(request.lockfile),
        host_profile=request.host_profile,
        build_profile=request.build_profile,
        output_folder=str(request.output_folder),
        download_cache=str(request.cache_dir),
        graph_output=str(request.graph_file),
        attempt_timeout_seconds=request.attempt_timeout_seconds,
    )
    execute_gate = gate_runner or (
        lambda requested, provided_secrets: run_dependency_gate(
            requested,
            secrets=provided_secrets,
        )
    )
    gate_started = clock()
    conclusion = execute_gate(gate_request, secret_values)
    conan_seconds = clock() - gate_started
    if not conclusion.success:
        raise RuntimeError(conclusion.diagnostic)
    if conclusion.dependency_path != _expected_dependency_path(request.restore):
        raise RuntimeError("strict Gate dependency path does not match cache restoration")

    graph = read_graph_evidence(request.graph_file)
    toolchain = request.output_folder / "conan_toolchain.cmake"
    build_command = [
        "colcon",
        "build",
        "--cmake-args",
        f"-DCMAKE_TOOLCHAIN_FILE={toolchain}",
        "-DCMAKE_BUILD_TYPE=Release",
        "-DBUILD_TESTING=ON",
    ]
    build_started = clock()
    build_result = build_runner(build_command)
    build_seconds = clock() - build_started
    if build_result.returncode != 0:
        output = "\n".join(
            part for part in (build_result.stderr, build_result.stdout) if part
        )
        terminal = classify_terminal_failure("build", output, secrets=secret_values)
        raise RuntimeError(terminal.diagnostic)

    after = inspect_download_cache(request.cache_dir, secrets=secret_values)
    if after.files == 0:
        raise RuntimeError("strict dependency preparation produced an empty download cache")
    if request.restore.kind == RestoreKind.EXACT and before != after:
        raise RuntimeError("Warm cache payload changed during an exact-key run")
    pending_save = (
        request.sample_role == SampleRole.PRODUCER
        and request.restore.kind != RestoreKind.EXACT
    )
    capacity = evaluate_cache_capacity(
        after.bytes,
        request.repository_cache_bytes,
        pending_save=pending_save,
    )
    component_total = request.restore_seconds + conan_seconds + build_seconds
    if request.total_start_unix_ms:
        total_seconds = (wall_clock_ms() - request.total_start_unix_ms) / 1000
        if total_seconds < 0:
            raise RuntimeError("total canary timing is invalid")
    else:
        total_seconds = component_total
    return CanaryEvidence(
        sample_role=request.sample_role,
        identity=request.identity,
        restore=request.restore,
        cache_before=before,
        cache_after=after,
        graph=graph,
        capacity=capacity,
        attempts=conclusion.attempts,
        restore_seconds=request.restore_seconds,
        conan_seconds=conan_seconds,
        build_seconds=build_seconds,
        total_seconds=total_seconds,
        recovery_from_generation=recovery_from_generation,
        recovery_control_key=request.recovery_control_key.strip(),
        warm_payload_enforcement=(
            "read-only-download-payload-mount"
            if request.restore.kind == RestoreKind.EXACT and request.cache_read_only
            else ""
        ),
    )
