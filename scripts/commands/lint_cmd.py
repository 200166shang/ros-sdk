"""lint and format sub-commands."""

from __future__ import annotations

import click

from scripts.utils.workspace import WorkspaceManager


@click.command()
def lint_cmd() -> None:
    """Check code style (dry-run) and run clang-tidy."""
    WorkspaceManager().lint()


@click.command(name="format")
def format_cmd() -> None:
    """Format code in-place with clang-format."""
    WorkspaceManager().format()
