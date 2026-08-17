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
    DockerManager().exec("bash", "-c", gazebo_launch_script())


def gazebo_launch_script() -> str:
    """Return the command used to launch Gazebo on the shared noVNC display."""
    return (
        "source /opt/ros/jazzy/setup.bash && "
        "export TURTLEBOT3_MODEL=burger && "
        'export DISPLAY="${DISPLAY:-novnc:0}" && '
        "export QT_X11_NO_MITSHM=1 && "
        "ros2 launch turtlebot3_gazebo turtlebot3_world.launch.py"
    )


def gazebo_stop_script() -> str:
    """Return a safe command for stopping the Gazebo launch process tree."""
    return (
        "for pid in $("
        "pgrep -f '[r]os2 launch turtlebot3_gazebo'; "
        "ps -eo pid=,args= | "
        "awk -v self=$$ '$1 != self && $0 ~ /[g]z sim/ {print $1}'"
        "); do "
        'kill "$pid" 2>/dev/null || true; '
        "done"
    )


@gazebo_cmd.command()
def stop() -> None:
    """Kill Gazebo processes inside the ros2 container."""
    DockerManager().exec("bash", "-c", gazebo_stop_script())
