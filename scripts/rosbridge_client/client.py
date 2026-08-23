"""Python client for the first RosBridge Pro runtime contract."""

from __future__ import annotations

from dataclasses import dataclass

import grpc

from scripts.rosbridge_client import delivery_pb2
from scripts.rosbridge_client import delivery_pb2_grpc
from scripts.rosbridge_client import runtime_health_pb2
from scripts.rosbridge_client import runtime_health_pb2_grpc


@dataclass(frozen=True)
class HealthStatus:
    """Observable runtime liveness and delivery readiness."""

    alive: bool
    delivery_ready: bool
    readiness_reason: str


@dataclass(frozen=True)
class DeliveryStatus:
    """Observable state of one simulated delivery request."""

    task_id: str
    request_id: str
    pickup_location: str
    dropoff_location: str
    state: int
    current_target: str
    remaining_distance_m: float | None


class RuntimeClient:
    """Call the runtime without requiring ROS 2 in the Python process."""

    def __init__(self, address: str, timeout_seconds: float = 2.0) -> None:
        self._channel = grpc.insecure_channel(address)
        self._stub = runtime_health_pb2_grpc.RuntimeServiceStub(self._channel)
        self._delivery_stub = delivery_pb2_grpc.DeliveryServiceStub(self._channel)
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

    def create_delivery(
        self, request_id: str, pickup_location: str, dropoff_location: str
    ) -> DeliveryStatus:
        """Create a delivery and return its immediate task snapshot."""
        response = self._delivery_stub.CreateDelivery(
            delivery_pb2.CreateDeliveryRequest(
                request_id=request_id,
                pickup_location=pickup_location,
                dropoff_location=dropoff_location,
            ),
            timeout=self._timeout_seconds,
        )
        return self._to_delivery_status(response)

    def get_delivery(self, task_id: str) -> DeliveryStatus:
        """Return the latest snapshot for an accepted delivery."""
        response = self._delivery_stub.GetDelivery(
            delivery_pb2.GetDeliveryRequest(task_id=task_id),
            timeout=self._timeout_seconds,
        )
        return self._to_delivery_status(response)

    def confirm_pickup(self, task_id: str) -> DeliveryStatus:
        """Confirm pickup and return the resulting delivery snapshot."""
        response = self._delivery_stub.ConfirmPickup(
            delivery_pb2.ConfirmDeliveryRequest(task_id=task_id),
            timeout=self._timeout_seconds,
        )
        return self._to_delivery_status(response)

    def confirm_dropoff(self, task_id: str) -> DeliveryStatus:
        """Confirm dropoff and return the resulting delivery snapshot."""
        response = self._delivery_stub.ConfirmDropoff(
            delivery_pb2.ConfirmDeliveryRequest(task_id=task_id),
            timeout=self._timeout_seconds,
        )
        return self._to_delivery_status(response)

    def cancel_delivery(self, task_id: str) -> DeliveryStatus:
        """Cancel a delivery and return the resulting delivery snapshot."""
        response = self._delivery_stub.CancelDelivery(
            delivery_pb2.CancelDeliveryRequest(task_id=task_id),
            timeout=self._timeout_seconds,
        )
        return self._to_delivery_status(response)

    @staticmethod
    def _to_delivery_status(response: delivery_pb2.DeliverySnapshot) -> DeliveryStatus:
        remaining_distance_m = (
            response.remaining_distance_m
            if response.HasField("remaining_distance_m")
            else None
        )
        return DeliveryStatus(
            task_id=response.task_id,
            request_id=response.request_id,
            pickup_location=response.pickup_location,
            dropoff_location=response.dropoff_location,
            state=response.state,
            current_target=response.current_target,
            remaining_distance_m=remaining_distance_m,
        )

    def close(self) -> None:
        """Release the underlying gRPC channel."""
        self._channel.close()

    def __enter__(self) -> "RuntimeClient":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()
