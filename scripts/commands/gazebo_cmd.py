"""gazebo sub-commands: start, stop."""

from __future__ import annotations

import click

from scripts.utils.docker import DockerManager


@click.group()
def gazebo_cmd() -> None:
    """Manage the Gazebo simulation."""


@gazebo_cmd.command()
def start() -> None:
    """Launch Gazebo + TurtleBot3 inside the ros2 container."""
    DockerManager().exec(
        "bash", "-c",
        "Xvfb :99 -screen 0 1280x720x24 & "
        "sleep 1 && "
        "source /opt/ros/jazzy/setup.bash && "
        "export TURTLEBOT3_MODEL=burger && "
        "ros2 launch turtlebot3_gazebo turtlebot3_world.launch.py",
    )


@gazebo_cmd.command()
def stop() -> None:
    """Kill Gazebo processes inside the ros2 container."""
    DockerManager().exec("bash", "-c", "pkill -f gazebo || true")
