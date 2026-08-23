"""Command-line Python client for RosBridge Pro."""

from __future__ import annotations

import json

import click
import grpc

from scripts.rosbridge_client import RuntimeClient, delivery_pb2
from scripts.rosbridge_client.client import DeliveryStatus


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


@main.command("create-delivery")
@click.option("--address", default="127.0.0.1:8765", show_default=True)
@click.option("--request-id", required=True)
@click.option("--pickup", required=True)
@click.option("--dropoff", required=True)
def create_delivery(address: str, request_id: str, pickup: str, dropoff: str) -> None:
    """Create a delivery and print its immediate task snapshot."""
    try:
        with RuntimeClient(address) as runtime_client:
            status = runtime_client.create_delivery(request_id, pickup, dropoff)
    except grpc.RpcError as error:
        raise click.ClickException(f"create delivery failed: {error.code().name}") from error

    click.echo(json.dumps(_delivery_payload(status), ensure_ascii=False))


@main.command("get-delivery")
@click.option("--address", default="127.0.0.1:8765", show_default=True)
@click.option("--task-id", required=True)
def get_delivery(address: str, task_id: str) -> None:
    """Print the latest delivery task snapshot."""
    try:
        with RuntimeClient(address) as runtime_client:
            status = runtime_client.get_delivery(task_id)
    except grpc.RpcError as error:
        raise click.ClickException(f"get delivery failed: {error.code().name}") from error

    click.echo(json.dumps(_delivery_payload(status), ensure_ascii=False))


@main.command("confirm-pickup")
@click.option("--address", default="127.0.0.1:8765", show_default=True)
@click.option("--task-id", required=True)
def confirm_pickup(address: str, task_id: str) -> None:
    """Confirm pickup and print the resulting delivery snapshot."""
    try:
        with RuntimeClient(address) as runtime_client:
            status = runtime_client.confirm_pickup(task_id)
    except grpc.RpcError as error:
        raise click.ClickException(f"confirm pickup failed: {error.code().name}") from error

    click.echo(json.dumps(_delivery_payload(status), ensure_ascii=False))


@main.command("confirm-dropoff")
@click.option("--address", default="127.0.0.1:8765", show_default=True)
@click.option("--task-id", required=True)
def confirm_dropoff(address: str, task_id: str) -> None:
    """Confirm dropoff and print the resulting delivery snapshot."""
    try:
        with RuntimeClient(address) as runtime_client:
            status = runtime_client.confirm_dropoff(task_id)
    except grpc.RpcError as error:
        raise click.ClickException(f"confirm dropoff failed: {error.code().name}") from error

    click.echo(json.dumps(_delivery_payload(status), ensure_ascii=False))


@main.command("cancel-delivery")
@click.option("--address", default="127.0.0.1:8765", show_default=True)
@click.option("--task-id", required=True)
def cancel_delivery(address: str, task_id: str) -> None:
    """Cancel a delivery and print the resulting delivery snapshot."""
    try:
        with RuntimeClient(address) as runtime_client:
            status = runtime_client.cancel_delivery(task_id)
    except grpc.RpcError as error:
        raise click.ClickException(f"cancel delivery failed: {error.code().name}") from error

    click.echo(json.dumps(_delivery_payload(status), ensure_ascii=False))


def _delivery_payload(status: DeliveryStatus) -> dict[str, object]:
    """Convert a delivery status into stable CLI JSON fields."""
    return {
        "task_id": status.task_id,
        "request_id": status.request_id,
        "pickup_location": status.pickup_location,
        "dropoff_location": status.dropoff_location,
        "state": delivery_pb2.DeliveryState.Name(status.state),
        "current_target": status.current_target,
        "remaining_distance_m": status.remaining_distance_m,
    }


if __name__ == "__main__":
    main()
