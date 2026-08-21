"""Start and watch a fixed-target navigation task from the host machine."""

from __future__ import annotations

import argparse
import pathlib
import sys
import tempfile
import threading

import grpc
from grpc_tools import protoc


def load_generated_modules(output_dir: pathlib.Path) -> tuple[object, object]:
    """Generate and import Python modules for the navigation protocol."""
    proto = pathlib.Path(__file__).parents[1] / "src/ros2_sdk/proto/navigation_smoke.proto"
    result = protoc.main(
        [
            "grpc_tools.protoc",
            f"--proto_path={proto.parent}",
            f"--python_out={output_dir}",
            f"--grpc_python_out={output_dir}",
            str(proto),
        ]
    )
    if result != 0:
        raise RuntimeError(f"failed to generate Python gRPC modules: exit {result}")

    sys.path.insert(0, str(output_dir))
    import navigation_smoke_pb2 as messages  # noqa: PLC0415
    import navigation_smoke_pb2_grpc as services  # noqa: PLC0415

    return messages, services


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", default="127.0.0.1:8765")
    parser.add_argument("--target", default="pickup_a")
    parser.add_argument("--timeout", type=float, default=70.0)
    parser.add_argument(
        "--cancel-after",
        type=float,
        default=None,
        help="request cancellation after this many seconds while watching",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    with tempfile.TemporaryDirectory(prefix="ros_sdk_navigation_proto_") as directory:
        messages, services = load_generated_modules(pathlib.Path(directory))
        with grpc.insecure_channel(args.address) as channel:
            stub = services.NavigationRpcStub(channel)
            health = stub.Health(messages.HealthRequest(), timeout=3.0)
            print(f"health.ready={health.ready} message={health.message}")
            started = stub.StartNavigation(
                messages.StartNavigationRequest(target_name=args.target), timeout=3.0
            )
            task = started.task
            print(f"task.id={task.task_id} state={task.state} message={task.message}")
            cancel_stop = threading.Event()
            cancel_thread = None
            if args.cancel_after is not None:
                def cancel_later() -> None:
                    if cancel_stop.wait(args.cancel_after):
                        return
                    try:
                        canceled = stub.CancelNavigation(
                            messages.CancelNavigationRequest(task_id=task.task_id), timeout=3.0
                        )
                        print(f"cancel requested state={canceled.task.state}")
                    except grpc.RpcError as error:
                        print(f"cancel failed: {error}", file=sys.stderr)

                cancel_thread = threading.Thread(target=cancel_later, daemon=True)
                cancel_thread.start()
            try:
                events = stub.WatchNavigation(
                    messages.WatchNavigationRequest(task_id=task.task_id), timeout=args.timeout
                )
                last = task
                for event in events:
                    last = event.task
                    print(
                        f"task.id={last.task_id} state={last.state} "
                        f"feedback={last.feedback} message={last.message}"
                    )
            except grpc.RpcError as error:
                print(f"watch failed: {error}", file=sys.stderr)
                return 1
            finally:
                cancel_stop.set()
                if cancel_thread is not None:
                    cancel_thread.join()

    return 0 if last.state in (messages.TASK_SUCCEEDED, messages.TASK_CANCELED) else 1


if __name__ == "__main__":
    raise SystemExit(main())
