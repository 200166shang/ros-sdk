"""lint and format sub-commands."""

from __future__ import annotations

import click

from scripts.utils.workspace import WorkspaceManager


@click.command()
def lint_cmd() -> None:
    """Check formatting and run incremental clang-tidy for PR changes."""
    WorkspaceManager().lint()


@click.command(name="format")
def format_cmd() -> None:
    """Format code in-place with clang-format."""
    WorkspaceManager().format()
