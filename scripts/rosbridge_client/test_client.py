"""Unit tests for the Python runtime client mapping."""

from __future__ import annotations

import unittest
from unittest import mock

import grpc

from scripts.rosbridge_client import client, delivery_pb2, runtime_health_pb2


class FakeRpcError(grpc.RpcError):
    def code(self) -> grpc.StatusCode:
        return grpc.StatusCode.FAILED_PRECONDITION

    def details(self) -> str:
        return "NOT_READY: delivery navigation capability is not ready"


class RuntimeClientTests(unittest.TestCase):
    def test_health_maps_the_external_response(self) -> None:
        response = runtime_health_pb2.HealthResponse(
            alive=True,
            delivery_ready=False,
            readiness_reason="delivery capability is not available yet",
        )
        stub = mock.Mock()
        stub.Health.return_value = response

        with mock.patch.object(client.runtime_health_pb2_grpc, "RuntimeServiceStub",
                               return_value=stub):
            with client.RuntimeClient("127.0.0.1:8765") as runtime_client:
                status = runtime_client.health()

        stub.Health.assert_called_once()
        self.assertEqual(
            status,
            client.HealthStatus(
                alive=True,
                delivery_ready=False,
                readiness_reason="delivery capability is not available yet",
            ),
        )

    def test_create_delivery_maps_the_initial_snapshot(self) -> None:
        response = delivery_pb2.DeliverySnapshot(
            task_id="task-1",
            request_id="request-1",
            pickup_location="pickup_a",
            dropoff_location="dropoff_a",
            state=delivery_pb2.STARTING,
        )
        stub = mock.Mock()
        stub.CreateDelivery.return_value = response

        with mock.patch.object(client.delivery_pb2_grpc, "DeliveryServiceStub", return_value=stub):
            with client.RuntimeClient("127.0.0.1:8765") as runtime_client:
                status = runtime_client.create_delivery("request-1", "pickup_a", "dropoff_a")

        stub.CreateDelivery.assert_called_once()
        self.assertEqual(
            status,
            client.DeliveryStatus(
                task_id="task-1",
                request_id="request-1",
                pickup_location="pickup_a",
                dropoff_location="dropoff_a",
                state=delivery_pb2.STARTING,
                current_target="",
                remaining_distance_m=None,
            ),
        )

    def test_get_delivery_maps_current_target_and_distance(self) -> None:
        response = delivery_pb2.DeliverySnapshot(
            task_id="task-1",
            request_id="request-1",
            pickup_location="pickup_a",
            dropoff_location="dropoff_a",
            state=delivery_pb2.NAVIGATING_TO_PICKUP,
            current_target="pickup_a",
            remaining_distance_m=1.25,
        )
        stub = mock.Mock()
        stub.GetDelivery.return_value = response

        with mock.patch.object(client.delivery_pb2_grpc, "DeliveryServiceStub", return_value=stub):
            with client.RuntimeClient("127.0.0.1:8765") as runtime_client:
                status = runtime_client.get_delivery("task-1")

        stub.GetDelivery.assert_called_once()
        self.assertEqual(status.state, delivery_pb2.NAVIGATING_TO_PICKUP)
        self.assertEqual(status.current_target, "pickup_a")
        self.assertEqual(status.remaining_distance_m, 1.25)

    def test_confirm_pickup_maps_the_updated_snapshot(self) -> None:
        response = delivery_pb2.DeliverySnapshot(
            task_id="task-1",
            request_id="request-1",
            pickup_location="pickup_a",
            dropoff_location="dropoff_a",
            state=delivery_pb2.NAVIGATING_TO_DROPOFF,
            current_target="dropoff_a",
        )
        stub = mock.Mock()
        stub.ConfirmPickup.return_value = response

        with mock.patch.object(client.delivery_pb2_grpc, "DeliveryServiceStub", return_value=stub):
            with client.RuntimeClient("127.0.0.1:8765") as runtime_client:
                status = runtime_client.confirm_pickup("task-1")

        stub.ConfirmPickup.assert_called_once()
        self.assertEqual(status.state, delivery_pb2.NAVIGATING_TO_DROPOFF)
        self.assertEqual(status.current_target, "dropoff_a")

    def test_confirm_dropoff_maps_the_completed_snapshot(self) -> None:
        response = delivery_pb2.DeliverySnapshot(
            task_id="task-1",
            request_id="request-1",
            pickup_location="pickup_a",
            dropoff_location="dropoff_a",
            state=delivery_pb2.COMPLETED,
        )
        stub = mock.Mock()
        stub.ConfirmDropoff.return_value = response

        with mock.patch.object(client.delivery_pb2_grpc, "DeliveryServiceStub", return_value=stub):
            with client.RuntimeClient("127.0.0.1:8765") as runtime_client:
                status = runtime_client.confirm_dropoff("task-1")

        stub.ConfirmDropoff.assert_called_once()
        self.assertEqual(status.state, delivery_pb2.COMPLETED)

    def test_cancel_delivery_maps_the_canceling_snapshot(self) -> None:
        response = delivery_pb2.DeliverySnapshot(
            task_id="task-1",
            request_id="request-1",
            pickup_location="pickup_a",
            dropoff_location="dropoff_a",
            state=delivery_pb2.CANCELING,
            current_target="pickup_a",
        )
        stub = mock.Mock()
        stub.CancelDelivery.return_value = response

        with mock.patch.object(client.delivery_pb2_grpc, "DeliveryServiceStub", return_value=stub):
            with client.RuntimeClient("127.0.0.1:8765") as runtime_client:
                status = runtime_client.cancel_delivery("task-1")

        stub.CancelDelivery.assert_called_once()
        self.assertEqual(status.state, delivery_pb2.CANCELING)
        self.assertEqual(status.current_target, "pickup_a")

    def test_create_delivery_raises_stable_domain_error(self) -> None:
        stub = mock.Mock()
        stub.CreateDelivery.side_effect = FakeRpcError()

        with mock.patch.object(client.delivery_pb2_grpc, "DeliveryServiceStub", return_value=stub):
            with client.RuntimeClient("127.0.0.1:8765") as runtime_client:
                with self.assertRaises(client.DeliveryError) as raised:
                    runtime_client.create_delivery("request-1", "pickup_a", "dropoff_a")

        self.assertEqual(raised.exception.error_code, "NOT_READY")
        self.assertEqual(raised.exception.message, "delivery navigation capability is not ready")

    def test_get_delivery_maps_failure_details(self) -> None:
        response = delivery_pb2.DeliverySnapshot(
            task_id="task-1",
            request_id="request-1",
            pickup_location="pickup_a",
            dropoff_location="dropoff_a",
            state=delivery_pb2.FAILED,
            failure_code="UNREACHABLE",
            failure_reason="navigation goal did not succeed",
        )
        stub = mock.Mock()
        stub.GetDelivery.return_value = response

        with mock.patch.object(client.delivery_pb2_grpc, "DeliveryServiceStub", return_value=stub):
            with client.RuntimeClient("127.0.0.1:8765") as runtime_client:
                status = runtime_client.get_delivery("task-1")

        self.assertEqual(status.failure_code, "UNREACHABLE")
        self.assertEqual(status.failure_reason, "navigation goal did not succeed")


if __name__ == "__main__":
    unittest.main()
