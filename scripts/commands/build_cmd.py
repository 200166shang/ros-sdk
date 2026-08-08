"""build sub-command."""

from __future__ import annotations

import click

from scripts.utils.workspace import WorkspaceManager


@click.command()
@click.option("--clean", is_flag=True, help="Remove build/ install/ log/ before building.")
def build_cmd(clean: bool) -> None:
    """Build the project (conan install + colcon build)."""
    WorkspaceManager().build(clean=clean)
