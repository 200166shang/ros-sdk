"""Runtime process commands."""

from __future__ import annotations

import shlex
import time

import click
import grpc

from scripts.rosbridge_client import RuntimeClient
from scripts.utils.docker import DockerManager


@click.group(name="runtime")
def runtime_cmd() -> None:
    """Run the C++ RosBridge Pro runtime in the ros2 container."""


@runtime_cmd.command("start")
@click.option("--address", default="0.0.0.0:8765", show_default=True)
def start(address: str) -> None:
    """Start the runtime in the ros2 container."""
    command = (
        "source /opt/ros/${ROS_DISTRO:-jazzy}/setup.bash && "
        "source /workspace/install/setup.bash && "
        f"exec /workspace/install/ros2_sdk/lib/ros2_sdk/rosbridge_runtime "
        f"{shlex.quote(address)}"
    )
    DockerManager().exec_detached("bash", "-lc", command)
    _wait_for_health(address)


@runtime_cmd.command("stop")
def stop() -> None:
    """Stop the runtime process in the ros2 container."""
    DockerManager().exec(
        "bash",
        "-lc",
        "pkill -TERM -f '^/workspace/install/ros2_sdk/lib/ros2_sdk/rosbridge_runtime( |$)' || true",
    )


def _wait_for_health(address: str, timeout_seconds: float = 5.0) -> None:
    """Wait until the host-mapped runtime answers the health RPC."""
    host, separator, port_text = address.rpartition(":")
    if not separator or not port_text.isdigit():
        raise click.ClickException(f"invalid runtime address: {address}")

    connect_host = "127.0.0.1" if host in ("", "0.0.0.0") else host
    connect_address = f"{connect_host}:{port_text}"
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            with RuntimeClient(connect_address, timeout_seconds=0.2) as runtime_client:
                runtime_client.health()
            return
        except grpc.RpcError:
            time.sleep(0.1)

    raise click.ClickException(f"runtime health check did not pass on {address}")
