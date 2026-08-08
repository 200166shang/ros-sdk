"""test sub-command."""

from __future__ import annotations

import click

from scripts.utils.workspace import WorkspaceManager


@click.command()
@click.option("--filter", "filter_pattern", default=None, help="Only run tests matching this pattern.")
def test_cmd(filter_pattern: str | None) -> None:
    """Run tests (colcon test)."""
    WorkspaceManager().test(filter_pattern=filter_pattern)
