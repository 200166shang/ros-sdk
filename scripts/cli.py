"""RosBridge Pro — development CLI entry point."""

from __future__ import annotations

import click

from scripts.commands.docker_cmd import docker_cmd
from scripts.commands.build_cmd import build_cmd
from scripts.commands.test_cmd import test_cmd
from scripts.commands.lint_cmd import lint_cmd, format_cmd
from scripts.commands.gazebo_cmd import gazebo_cmd
from scripts.utils.workspace import WorkspaceManager


@click.group()
@click.version_option(version="0.1.0", message="RosBridge Pro CLI %(version)s")
def main() -> None:
    """RosBridge Pro — C++ robot runtime framework development tool."""


main.add_command(docker_cmd, name="docker")
main.add_command(build_cmd, name="build")
main.add_command(test_cmd, name="test")
main.add_command(lint_cmd, name="lint")
main.add_command(format_cmd, name="format")
main.add_command(gazebo_cmd, name="gazebo")


@main.command()
def shell() -> None:
    """Open an interactive bash shell inside the ros2 container."""
    from scripts.utils.docker import DockerManager
    DockerManager().exec("bash")


@main.command()
def ci() -> None:
    """Run the full CI pipeline: lint → build → test."""
    WorkspaceManager().ci()
