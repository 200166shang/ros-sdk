"""Implement repository CI commands for host and ros2 container execution."""

from __future__ import annotations

import base64
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Iterable, Mapping, Sequence


ENVIRONMENT_CHANGE_PATTERNS = (
    re.compile(r"^Dockerfile$"),
    re.compile(r"^docker/"),
    re.compile(r"^docker-compose\.yaml$"),
    re.compile(r"^conanfile\.txt$"),
    re.compile(r"^conan\.lock$"),
    re.compile(r"^src/ros2_sdk/(package\.xml|CMakeLists\.txt)$"),
)


def environment_changed(changed_files: Iterable[str]) -> bool:
    """Return whether a changed file invalidates the reusable CI image."""
    return any(
        pattern.match(path)
        for path in changed_files
        for pattern in ENVIRONMENT_CHANGE_PATTERNS
    )


def select_ci_image(
    environment_changed: bool,
    cache_available: bool,
    cached_image: str,
    local_image: str,
) -> tuple[str, bool]:
    """Choose the image and whether the workflow must build it locally."""
    should_build = environment_changed or not cache_available
    return (local_image if should_build else cached_image, should_build)


def _run(
    command: Sequence[str],
    *,
    env: dict[str, str] | None = None,
    quiet: bool = False,
) -> None:
    subprocess.run(
        command,
        check=True,
        env=env,
        stdout=subprocess.PIPE if quiet else None,
        stderr=subprocess.PIPE if quiet else None,
        text=True,
    )


def _try_run(command: Sequence[str]) -> bool:
    return subprocess.run(
        command,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ).returncode == 0


def _run_conan_install(command: Sequence[str]) -> None:
    result = subprocess.run(
        command,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.stdout:
        sys.stdout.write(result.stdout)
    if result.stderr:
        sys.stderr.write(result.stderr)
    result.check_returncode()


def _capture(command: Sequence[str]) -> str:
    return subprocess.check_output(command, text=True).strip()


def _env_flag(name: str, environ: Mapping[str, str] | None = None) -> bool:
    environment = os.environ if environ is None else environ
    return environment.get(name, "").lower() == "true"


def _compose_command() -> list[str]:
    if shutil.which("docker-compose"):
        return ["docker-compose"]
    try:
        subprocess.run(
            ["docker", "compose", "version"],
            capture_output=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as error:
        raise RuntimeError("neither 'docker compose' nor 'docker-compose' found") from error
    return ["docker", "compose"]


def _write_github_file(variable: str, value: str, filename_variable: str) -> None:
    filename = os.environ.get(filename_variable)
    if filename:
        with Path(filename).open("a", encoding="utf-8") as output:
            output.write(f"{variable}={value}\n")
    else:
        print(f"{variable}={value}")


def detect_changes() -> None:
    """Detect environment changes and write the GitHub job output."""
    base_sha = os.environ["BASE_SHA"]
    head_sha = os.environ["HEAD_SHA"]
    changed_files = _capture(["git", "diff", "--name-only", base_sha, head_sha]).splitlines()
    print("\n".join(changed_files))
    _write_github_file(
        "environment_changed",
        str(environment_changed(changed_files)).lower(),
        "GITHUB_OUTPUT",
    )


def prepare_image() -> None:
    """Pull the reusable image or build a local candidate when needed."""
    cached_image = os.environ["CI_IMAGE"]
    local_image = os.environ["LOCAL_CI_IMAGE"]
    changed = os.environ.get("ENVIRONMENT_CHANGED", "false").lower() == "true"

    cache_available = subprocess.run(
        ["docker", "pull", cached_image],
        check=False,
    ).returncode == 0
    image, should_build = select_ci_image(
        changed,
        cache_available,
        cached_image,
        local_image,
    )

    if should_build:
        build_command = [
            "docker",
            "build",
            "--build-arg",
            "BUILDKIT_INLINE_CACHE=1",
        ]
        if cache_available:
            build_command.extend(["--cache-from", cached_image])
        build_command.extend(
            [
                "--file",
                "docker/Dockerfile",
                "--target",
                "ci",
                "--tag",
                local_image,
                ".",
            ]
        )
        build_env = os.environ.copy()
        build_env["DOCKER_BUILDKIT"] = "1"
        _run(build_command, env=build_env)

    _write_github_file("ROSBRIDGE_IMAGE", image, "GITHUB_ENV")


def compose_up() -> None:
    """Start the requested Compose service."""
    command = _compose_command()
    command.extend(["--project-name", os.environ.get("COMPOSE_PROJECT_NAME", "rosbridge")])
    command.extend(["up", "--detach"])
    if _env_flag("COMPOSE_NO_DEPS"):
        command.append("--no-deps")
    service = os.environ.get("COMPOSE_SERVICE", "ros2")
    if service:
        command.append(service)
    _run(command)


def compose_down() -> None:
    """Stop and remove the workflow Compose project."""
    command = _compose_command()
    command.extend(
        [
            "--project-name",
            os.environ.get("COMPOSE_PROJECT_NAME", "rosbridge"),
            "down",
            "--remove-orphans",
        ]
    )
    _run(command)


def verify_arm64() -> None:
    """Verify the runner, image, container, and Conan host architecture."""
    if _capture(["uname", "-m"]) != "aarch64":
        raise RuntimeError("GitHub runner is not aarch64")
    if _capture(["docker", "exec", "ros2", "uname", "-m"]) != "aarch64":
        raise RuntimeError("ros2 container is not aarch64")
    image = os.environ["ROSBRIDGE_IMAGE"]
    if _capture(["docker", "image", "inspect", image, "--format", "{{.Architecture}}"]) != "arm64":
        raise RuntimeError("CI image is not arm64")
    _run(
        [
            "docker",
            "exec",
            "ros2",
            "bash",
            "-lc",
            'conan profile show -pr:h default | grep -Fx "arch=armv8"',
        ]
    )
    print("ARM64 build environment verified")


def _verify_conan_http() -> None:
    remote_url = os.environ["CONAN_REMOTE_URL"].rstrip("/")
    username = os.environ.get("CONAN_LOGIN_USERNAME", "")
    password = os.environ.get("CONAN_PASSWORD", "")

    def request(path: str, authenticated: bool = False) -> None:
        request = urllib.request.Request(remote_url + path)
        if authenticated:
            if not username or not password:
                raise RuntimeError("Conan remote credentials are not configured")
            credentials = f"{username}:{password}".encode()
            token = base64.b64encode(credentials).decode()
            request.add_header("Authorization", f"Basic {token}")
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                if response.status != 200:
                    raise RuntimeError(f"Conan remote returned HTTP {response.status}")
        except urllib.error.HTTPError as error:
            raise RuntimeError(f"Conan remote returned HTTP {error.code}") from error
        except urllib.error.URLError as error:
            raise RuntimeError(f"Conan remote is unreachable: {error.reason}") from error

    request("/v1/ping")
    request("/v2/users/authenticate", authenticated=True)
    print("Conan remote reachability and credentials verified")


def verify_conan(in_container: bool = False) -> None:
    """Verify Conan Server from the same ros2 container used by the build."""
    if not os.environ.get("CONAN_REMOTE_URL"):
        print("Conan remote not configured; skipping remote verification")
        return
    if in_container:
        _verify_conan_http()
        return
    _run(["docker", "exec", "ros2", "python3", "-m", "scripts.ci", "verify-conan", "--in-container"])


def conan_install_command(environ: Mapping[str, str] | None = None) -> list[str]:
    """Build the Conan install command from opt-in environment controls."""
    environment = os.environ if environ is None else environ
    build_policy = environment.get("CONAN_BUILD_POLICY", "missing")
    if build_policy not in ("missing", "never"):
        raise ValueError("CONAN_BUILD_POLICY must be 'missing' or 'never'")

    command = [
        "conan",
        "install",
        ".",
        "--lockfile=conan.lock",
        "--output-folder=build",
        f"--build={build_policy}",
        "-s",
        "build_type=Release",
        "-s",
        "compiler.cppstd=17",
    ]

    download_cache = environment.get("CONAN_DOWNLOAD_CACHE", "")
    if download_cache:
        if not Path(download_cache).is_absolute():
            raise ValueError("CONAN_DOWNLOAD_CACHE must be an absolute path")
        command.extend(["-cc", f"core.download:download_cache={download_cache}"])

    graph_file = environment.get("CONAN_GRAPH_FILE", "")
    if graph_file:
        if not Path(graph_file).is_absolute():
            raise ValueError("CONAN_GRAPH_FILE must be an absolute path")
        command.extend(["--format=json", f"--out-file={graph_file}"])

    if _env_flag("CONAN_REQUIRE_REMOTE", environment):
        remote_name = environment.get("CONAN_REMOTE_NAME", "rosbridge")
        command.append(f"--remote={remote_name}")

    return command


def _configure_conan_remote() -> None:
    """Configure the optional Conan remote, with strict mode for the cache Spike."""
    require_remote = _env_flag("CONAN_REQUIRE_REMOTE")
    remote_name = os.environ.get("CONAN_REMOTE_NAME", "rosbridge")
    remote_url = os.environ.get("CONAN_REMOTE_URL", "")
    username = os.environ.get("CONAN_LOGIN_USERNAME", "")
    password = os.environ.get("CONAN_PASSWORD", "")

    if require_remote and not remote_url:
        raise RuntimeError("CONAN_REMOTE_URL is required when CONAN_REQUIRE_REMOTE=true")
    if require_remote and (not username or not password):
        raise RuntimeError("Conan remote credentials are required when CONAN_REQUIRE_REMOTE=true")

    _try_run(["conan", "remote", "disable", remote_name])
    if not remote_url:
        print("Conan remote not configured; using default remotes")
        return

    try:
        _run(
            ["conan", "remote", "add", remote_name, remote_url, "--index", "0", "--force"],
            quiet=True,
        )
        if username and password:
            _run(
                ["conan", "remote", "login", remote_name, username, "-p", password],
                quiet=True,
            )
            _run(["conan", "remote", "enable", remote_name], quiet=True)
            print(f"Conan remote enabled: {remote_name}")
        else:
            _try_run(["conan", "remote", "disable", remote_name])
            print("Conan remote unavailable or unauthenticated; using fallback")
    except subprocess.CalledProcessError:
        _try_run(["conan", "remote", "disable", remote_name])
        if require_remote:
            raise RuntimeError("Conan required remote setup failed") from None
        print("Conan remote unavailable or unauthenticated; using fallback")


def _install_conan_dependencies() -> None:
    """Install Conan dependencies and explain strict cache misses."""
    command = conan_install_command()
    try:
        _run_conan_install(command)
    except subprocess.CalledProcessError as error:
        diagnostics = f"{error.output or ''}\n{error.stderr or ''}"
        if "--build=never" in command and "missing binary" in diagnostics.lower():
            raise RuntimeError(
                "ARM64 dependency preparation required: the server is unavailable or "
                "the exact package is missing"
            ) from error
        raise


def build_workspace(clean: bool = False) -> None:
    """Install Conan dependencies and build the ROS workspace in the container."""
    if clean:
        for directory in ("build", "install", "log"):
            shutil.rmtree(directory, ignore_errors=True)

    _configure_conan_remote()

    print(f"Conan version: {_capture(['conan', '--version'])}")
    print(
        "Conan host settings: arch=armv8 compiler=gcc "
        "compiler.version=13 compiler.cppstd=17 build_type=Release"
    )
    started = time.monotonic()
    _install_conan_dependencies()
    print(f"Conan install elapsed: {int(time.monotonic() - started)}s")
    _run(
        [
            "bash",
            "-lc",
            "source build/conanbuild.sh && "
            "colcon build --base-paths src --symlink-install "
            "--cmake-args "
            "-DCMAKE_TOOLCHAIN_FILE=/workspace/build/conan_toolchain.cmake "
            "-DCMAKE_BUILD_TYPE=Release "
            "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON",
        ]
    )


def publish_image() -> None:
    """Publish the validated candidate image under the configured CI tag."""
    candidate = os.environ["CANDIDATE_IMAGE"]
    target = os.environ["CI_IMAGE"]
    _run(["docker", "tag", candidate, target])
    _run(["docker", "push", target])
