"""Command line entry point for repository CI helpers."""

from __future__ import annotations

import argparse

from scripts.ci import commands


def main() -> None:
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

    args = parser.parse_args()
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


if __name__ == "__main__":
    main()
