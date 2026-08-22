"""Python client for the first RosBridge Pro runtime contract."""

from __future__ import annotations

from dataclasses import dataclass

import grpc

from scripts.rosbridge_client import runtime_health_pb2
from scripts.rosbridge_client import runtime_health_pb2_grpc


@dataclass(frozen=True)
class HealthStatus:
    """Observable runtime liveness and delivery readiness."""

    alive: bool
    delivery_ready: bool
    readiness_reason: str


class RuntimeClient:
    """Call the runtime without requiring ROS 2 in the Python process."""

    def __init__(self, address: str, timeout_seconds: float = 2.0) -> None:
        self._channel = grpc.insecure_channel(address)
        self._stub = runtime_health_pb2_grpc.RuntimeServiceStub(self._channel)
        self._timeout_seconds = timeout_seconds

    def health(self) -> HealthStatus:
        """Return the current runtime health or raise ``grpc.RpcError``."""
        response = self._stub.Health(
            runtime_health_pb2.HealthRequest(),
            timeout=self._timeout_seconds,
        )
        return HealthStatus(
            alive=response.alive,
            delivery_ready=response.delivery_ready,
            readiness_reason=response.readiness_reason,
        )

    def close(self) -> None:
        """Release the underlying gRPC channel."""
        self._channel.close()

    def __enter__(self) -> "RuntimeClient":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()
