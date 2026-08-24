"""Command line entry point for repository CI helpers."""

from __future__ import annotations

import argparse
import os

from scripts.ci import commands, orchestration


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
    dependency_gate.add_argument("--attempt-timeout", type=int, default=420)

    args = parser.parse_args()
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
