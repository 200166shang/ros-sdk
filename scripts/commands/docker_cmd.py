"""docker sub-commands: up, down, shell, build-image, ps."""

from __future__ import annotations

import click

from scripts.utils.docker import DockerManager


@click.group(name="docker", invoke_without_command=True)
@click.pass_context
def docker_cmd(ctx: click.Context) -> None:
    """Manage the Docker development environment."""
    if ctx.invoked_subcommand is None:
        DockerManager().ps()


@docker_cmd.command()
def up() -> None:
    """Start containers in the background."""
    DockerManager().up()


@docker_cmd.command()
def down() -> None:
    """Stop and remove containers."""
    DockerManager().down()


@docker_cmd.command("build-image")
def build_image() -> None:
    """Build (or rebuild) the ros2 Docker image."""
    DockerManager().build()


@docker_cmd.command()
def shell() -> None:
    """Open an interactive shell inside the ros2 container."""
    DockerManager().exec("bash")
