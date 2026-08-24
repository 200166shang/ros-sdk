"""Command line entry point for repository CI helpers."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from scripts.ci import cache_canary, commands, orchestration


def main() -> int:
    parser = argparse.ArgumentParser(description="RosBridge Pro CI helpers")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("detect-changes")
    subparsers.add_parser("prepare-image")
    subparsers.add_parser("compose-up")
    subparsers.add_parser("compose-down")
    subparsers.add_parser("verify-arm64")
    verify_conan = subparsers.add_parser("verify-conan")
    verify_conan.add_argument("--in-container", action="store_true")
    build_workspace = subparsers.add_parser("build-workspace")
    build_workspace.add_argument("--clean", action="store_true")
    subparsers.add_parser("publish-image")
    plan = subparsers.add_parser(
        "plan",
        help="emit the shared execution plan without changing workflow state",
    )
    plan.add_argument(
        "--event",
        required=True,
        choices=[event.value for event in orchestration.EventType],
    )
    plan.add_argument(
        "--cache-state",
        required=True,
        choices=[state.value for state in orchestration.CacheState],
    )
    plan.add_argument("--changed-file", action="append", default=[])
    dependency_gate = subparsers.add_parser(
        "dependency-gate",
        help="install the locked ARM64 graph from one required Conan remote",
    )
    dependency_gate.add_argument("--remote", required=True)
    dependency_gate.add_argument(
        "--cache-state",
        required=True,
        choices=[state.value for state in orchestration.CacheState],
    )
    dependency_gate.add_argument("--lockfile", default="conan.lock")
    dependency_gate.add_argument("--host-profile", default="default")
    dependency_gate.add_argument("--build-profile", default="default")
    dependency_gate.add_argument("--output-folder", default="build")
    dependency_gate.add_argument("--download-cache")
    dependency_gate.add_argument("--graph-output")
    dependency_gate.add_argument("--attempt-timeout", type=int, default=420)
    cache_identity = subparsers.add_parser(
        "cache-identity",
        help="emit the normalized Conan download-cache identity",
    )
    cache_identity.add_argument("--generation", required=True)
    cache_identity.add_argument("--lockfile", default="conan.lock")
    cache_identity.add_argument("--dependency-file", action="append")
    cache_identity.add_argument("--host-profile", default="default")
    cache_identity.add_argument("--build-profile", default="default")
    cache_run = subparsers.add_parser(
        "cache-run",
        help="verify Server authority and emit credential-free cache canary evidence",
    )
    cache_run.add_argument("--generation", required=True)
    cache_run.add_argument(
        "--sample-role",
        required=True,
        choices=[role.value for role in cache_canary.SampleRole],
    )
    cache_run.add_argument("--expected-key", required=True)
    cache_run.add_argument("--matched-key", default="")
    cache_run.add_argument("--restore-failed", action="store_true")
    cache_run.add_argument("--restore-seconds", type=float, required=True)
    cache_run.add_argument("--repository-cache-bytes", type=int, required=True)
    cache_run.add_argument("--remote", required=True)
    cache_run.add_argument("--remote-url", required=True)
    cache_run.add_argument("--cache-dir", type=Path, required=True)
    cache_run.add_argument("--graph-output", type=Path, required=True)
    cache_run.add_argument("--output-folder", type=Path, required=True)
    cache_run.add_argument("--result-output", type=Path, required=True)
    cache_run.add_argument("--lockfile", default="conan.lock")
    cache_run.add_argument("--dependency-file", action="append")
    cache_run.add_argument("--host-profile", default="default")
    cache_run.add_argument("--build-profile", default="default")
    cache_run.add_argument("--attempt-timeout", type=int, default=420)

    args = parser.parse_args()
    if args.command == "cache-identity":
        repository = Path.cwd()
        evidence = cache_canary.collect_environment_evidence(
            repository,
            host_profile=args.host_profile,
            build_profile=args.build_profile,
        )
        dependency_files = args.dependency_file or ["conanfile.txt"]
        identity = cache_canary.build_cache_identity(
            generation=args.generation,
            evidence=evidence,
            lockfile=repository / args.lockfile,
            dependency_files=[repository / path for path in dependency_files],
        )
        print(json.dumps(identity.to_dict(), indent=2, sort_keys=True))
        return 0
    if args.command == "cache-run":
        repository = Path.cwd()
        dependency_files = args.dependency_file or ["conanfile.txt"]
        secret_names = (
            "CONAN_LOGIN_USERNAME",
            "CONAN_PASSWORD",
            "CONAN_TOKEN",
        )
        secrets = tuple(os.environ.get(name, "") for name in secret_names)
        cache_canary.configure_required_remote(
            args.remote,
            args.remote_url,
            secrets=secrets,
        )
        evidence = cache_canary.collect_environment_evidence(
            repository,
            host_profile=args.host_profile,
            build_profile=args.build_profile,
        )
        identity = cache_canary.build_cache_identity(
            generation=args.generation,
            evidence=evidence,
            lockfile=repository / args.lockfile,
            dependency_files=[repository / path for path in dependency_files],
        )
        if identity.key != args.expected_key:
            raise RuntimeError("restored cache identity does not match the execution environment")
        restore = cache_canary.classify_cache_restore(
            identity,
            matched_key=args.matched_key,
            restore_failed=args.restore_failed,
        )
        args.graph_output.parent.mkdir(parents=True, exist_ok=True)
        args.output_folder.mkdir(parents=True, exist_ok=True)
        result = cache_canary.run_canary(
            cache_canary.CanaryRequest(
                sample_role=cache_canary.SampleRole(args.sample_role),
                identity=identity,
                restore=restore,
                cache_dir=args.cache_dir,
                graph_file=args.graph_output,
                output_folder=args.output_folder,
                remote_name=args.remote,
                restore_seconds=args.restore_seconds,
                repository_cache_bytes=args.repository_cache_bytes,
                lockfile=repository / args.lockfile,
                host_profile=args.host_profile,
                build_profile=args.build_profile,
                attempt_timeout_seconds=args.attempt_timeout,
            ),
            secrets=secrets,
        )
        payload = result.to_dict()
        if args.result_output.is_symlink():
            raise RuntimeError("canary result output must not be a symlink")
        args.result_output.parent.mkdir(parents=True, exist_ok=True)
        rendered = json.dumps(payload, allow_nan=False, indent=2, sort_keys=True) + "\n"
        args.result_output.write_text(rendered, encoding="utf-8")
        print(rendered, end="")
        return 0
    if args.command == "plan":
        execution_plan = orchestration.create_execution_plan(
            orchestration.EventType(args.event),
            args.changed_file,
            orchestration.CacheState(args.cache_state),
        )
        print(execution_plan.to_json())
        return 0
    if args.command == "dependency-gate":
        request = orchestration.GateRequest(
            remote_name=args.remote,
            cache_state=orchestration.CacheState(args.cache_state),
            lockfile=args.lockfile,
            host_profile=args.host_profile,
            build_profile=args.build_profile,
            output_folder=args.output_folder,
            download_cache=args.download_cache,
            graph_output=args.graph_output,
            attempt_timeout_seconds=args.attempt_timeout,
        )
        secret_names = (
            "CONAN_LOGIN_USERNAME",
            "CONAN_PASSWORD",
            "CONAN_TOKEN",
            "SSH_PRIVATE_KEY",
            "SSH_KNOWN_HOSTS",
        )
        conclusion = orchestration.run_dependency_gate(
            request,
            secrets=tuple(os.environ.get(name, "") for name in secret_names),
        )
        print(conclusion.to_json())
        return 0 if conclusion.success else 1

    handlers = {
        "detect-changes": commands.detect_changes,
        "prepare-image": commands.prepare_image,
        "compose-up": commands.compose_up,
        "compose-down": commands.compose_down,
        "verify-arm64": commands.verify_arm64,
        "verify-conan": lambda: commands.verify_conan(args.in_container),
        "build-workspace": lambda: commands.build_workspace(args.clean),
        "publish-image": commands.publish_image,
    }
    handlers[args.command]()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
