"""Call the temporary fixed-target navigation RPC from the host machine."""

from __future__ import annotations

import argparse
import pathlib
import sys
import tempfile

import grpc
from grpc_tools import protoc


def load_generated_modules(output_dir: pathlib.Path) -> tuple[object, object]:
    """Generate and import Python modules for the temporary smoke protocol."""
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
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    with tempfile.TemporaryDirectory(prefix="ros_sdk_navigation_proto_") as directory:
        messages, services = load_generated_modules(pathlib.Path(directory))
        with grpc.insecure_channel(args.address) as channel:
            stub = services.NavigationRpcStub(channel)
            health = stub.Health(messages.HealthRequest(), timeout=3.0)
            print(f"health.ready={health.ready} message={health.message}")
            response = stub.Navigate(
                messages.NavigateRequest(target_name=args.target), timeout=args.timeout
            )

    print(f"outcome={response.outcome} message={response.message}")
    return 0 if response.outcome == messages.NavigateResponse.SUCCEEDED else 1


if __name__ == "__main__":
    raise SystemExit(main())
