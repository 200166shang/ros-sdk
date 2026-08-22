"""Command-line Python client for RosBridge Pro."""

from __future__ import annotations

import json

import click
import grpc

from scripts.rosbridge_client import RuntimeClient


@click.group()
def main() -> None:
    """Call RosBridge Pro runtime capabilities."""


@main.command()
@click.option("--address", default="127.0.0.1:8765", show_default=True)
def health(address: str) -> None:
    """Print the runtime health response as JSON."""
    try:
        with RuntimeClient(address) as runtime_client:
            status = runtime_client.health()
    except grpc.RpcError as error:
        raise click.ClickException(f"runtime health request failed: {error.code().name}") from error

    click.echo(
        json.dumps(
            {
                "alive": status.alive,
                "delivery_ready": status.delivery_ready,
                "readiness_reason": status.readiness_reason,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
