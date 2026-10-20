"""Tests for MQTT client reconnection behaviour."""

from __future__ import annotations

from unittest.mock import Mock, call, patch

import pytest
from utils.mqtt import MqttClient


@pytest.fixture(autouse=True)
def reset_mqtt_client_singleton() -> None:
    """Prevent MQTT client state leaking between tests."""
    MqttClient._instances.clear()


@patch("utils.mqtt.mqtt.Client")
def test_restores_topic_subscriptions_on_connect(mock_client_cls: Mock) -> None:
    """Restore subscriptions after a broker restart creates a new session."""
    paho_client = mock_client_cls.return_value
    mqtt_client = MqttClient()

    def callback(_: object) -> None:
        pass

    mqtt_client.add_topic_callback("/mtrxpi/matrix/queue-content", callback)
    mqtt_client.add_topic_callback("/mtrxpi/matrix/brightness", callback)
    paho_client.reset_mock()

    mqtt_client._on_connect(paho_client, None, Mock(), Mock(is_failure=False), None)

    paho_client.subscribe.assert_has_calls(
        [
            call("/mtrxpi/matrix/brightness"),
            call("/mtrxpi/matrix/queue-content"),
        ],
        any_order=True,
    )
    assert paho_client.subscribe.call_count == 2


@patch("utils.mqtt.mqtt.Client")
def test_explicit_retain_false_overrides_default(mock_client_cls: Mock) -> None:
    """Transient messages stay transient when the client default is retained."""
    mqtt_client = MqttClient(retain=True)
    mqtt_client.publish("/mtrxpi/test", "payload", retain=False)

    assert mock_client_cls.return_value.publish.call_args.kwargs["retain"] is False
