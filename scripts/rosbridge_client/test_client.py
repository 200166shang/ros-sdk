"""Unit tests for the Python runtime client mapping."""

from __future__ import annotations

import unittest
from unittest import mock

from scripts.rosbridge_client import client, runtime_health_pb2


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


if __name__ == "__main__":
    unittest.main()
