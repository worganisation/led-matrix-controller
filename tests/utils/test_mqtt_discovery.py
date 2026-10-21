"""Discovery publishes current state while preserving retained command values."""

from __future__ import annotations

from json import loads
from typing import TYPE_CHECKING, cast
from unittest.mock import Mock, patch

import pytest
from content.dynamic_content import DynamicContent
from content.setting import (
    FrequencySetting,
    ParameterSetting,
    TransitionableFrequencySetting,
    TransitionableParameterSetting,
)
from main import get_library
from paho.mqtt.client import MQTTMessage
from utils.mqtt import MqttClient
from utils.mqtt_discovery import discovery_config, register_discovery

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture
def mqtt_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[MqttClient]:
    """Use the actual callback dispatch with a disconnected Paho client."""
    MqttClient._instances.clear()
    with (
        patch("utils.mqtt.mqtt.Client"),
        patch.dict("content.base._CONTENT_STORE", clear=True),
    ):
        client = MqttClient()
        for cls in (
            FrequencySetting,
            ParameterSetting,
            TransitionableFrequencySetting,
            TransitionableParameterSetting,
        ):
            monkeypatch.setattr(cls, "_MQTT_CLIENT", client, raising=False)
        yield client

    MqttClient._instances.clear()


def test_discovery_lifecycle_does_not_overwrite_state(mqtt_client: MqttClient) -> None:
    """Successful reconnects and HA births republish configurations and actual state."""
    paho = cast("Mock", mqtt_client._client)
    contents = tuple(item for item in get_library() if isinstance(item, DynamicContent))
    register_discovery(mqtt_client, contents)
    assert not paho.publish.called

    mqtt_client._on_connect(paho, None, Mock(), Mock(is_failure=True), None)
    assert not paho.publish.called

    mqtt_client._on_connect(paho, None, Mock(), Mock(is_failure=False), None)
    first_configs = paho.publish.call_args_list.copy()
    assert len(first_configs) == 70
    assert all(
        (call.args[0].endswith("/config") or call.args[0].endswith("/state"))
        and call.kwargs["retain"]
        and call.kwargs["qos"] == 1
        for call in first_configs
    )
    assert len({call.args[0] for call in first_configs}) == len(first_configs)

    callback = paho.message_callback_add.call_args.args[1]
    paho.reset_mock()
    mqtt_client._on_connect(paho, None, Mock(), Mock(is_failure=False), None)
    assert paho.publish.call_args_list == first_configs

    paho.reset_mock()
    message = MQTTMessage(topic=b"homeassistant/status")
    for payload in (b"offline", b"", b"unexpected"):
        message.payload = payload
        callback(paho, None, message)
    assert not paho.publish.called

    message.payload = b"online"
    callback(paho, None, message)
    assert paho.publish.call_args_list == first_configs


def test_discovery_preserves_control_contracts(mqtt_client: MqttClient) -> None:
    """Settings keep their IDs, bounds, enum choices and JSON command encoding."""
    contents = tuple(item for item in get_library() if isinstance(item, DynamicContent))
    register_discovery(mqtt_client, contents)
    mqtt_client._on_connect(
        mqtt_client._client,
        None,
        Mock(),
        Mock(is_failure=False),
        None,
    )
    paho = cast("Mock", mqtt_client._client)
    configs = {
        payload["unique_id"]: payload
        for call in paho.publish.call_args_list
        if call.args[0].endswith("/config") and (payload := loads(call.args[1]))
    }

    for content in contents:
        for setting in content.settings.values():
            if config := discovery_config(setting):
                topic, payload = config
                assert (
                    payload["unique_id"]
                    == f"mtrxpi_{content.id.replace('-', '_')}_{setting.slug}"
                )
                assert (
                    payload["default_entity_id"]
                    == f"{topic.split('/')[1]}.{payload['unique_id']}"
                )
                assert payload["command_topic"] == setting.mqtt_topic
                assert payload["state_topic"] == f"{setting.mqtt_topic}/state"

    rain = configs["mtrxpi_raining_grid_rain_chance"]
    assert (rain["min"], rain["max"], rain["step"], rain["mode"]) == (
        0,
        100,
        0.001,
        "box",
    )
    sorter = configs["mtrxpi_sorter_algorithm"]
    assert "Bubblesort" in sorter["options"]
    assert sorter["command_template"] == "{{ slugify(value) | tojson }}"
    switch = configs["mtrxpi_sorter_randomize_algorithm"]
    assert switch["payload_on"] == switch["state_on"] == "true"
    assert switch["payload_off"] == switch["state_off"] == "false"
    text = configs["mtrxpi_audio_visualiser_low_magnitude_hex_color"]
    assert text["command_template"] == "{{ value | tojson }}"
    assert text["value_template"] == "{{ value_json }}"
    assert "mtrxpi_combination_content" not in configs
    assert "mtrxpi_now_playing_track_metadata" not in configs


def test_retained_commands_restore_scaled_state_without_feedback(
    mqtt_client: MqttClient,
) -> None:
    """A saved percentage wins over defaults and is never divided a second time."""
    contents = tuple(item for item in get_library() if isinstance(item, DynamicContent))
    rain = next(item for item in contents if item.id == "raining-grid")
    setting = rain.settings["rain_chance"]
    setting.matrix = Mock()
    mqtt_client.add_topic_callback(setting.mqtt_topic, setting.on_message)
    paho = cast("Mock", mqtt_client._client)
    callback = paho.message_callback_add.call_args.args[1]
    register_discovery(mqtt_client, contents)
    mqtt_client._on_connect(paho, None, Mock(), Mock(is_failure=False), None)
    initial_states = {
        call.args[0]: loads(call.args[1])
        for call in paho.publish.call_args_list
        if call.args[0].endswith("/state")
    }
    assert len(initial_states) == 35
    assert initial_states[setting.state_topic] == 25
    assert initial_states[rain.settings["plant_growth_chance"].state_topic] == 1
    assert initial_states[
        rain.settings["leaf_growth_chance"].state_topic
    ] == pytest.approx(0.5)
    assert (
        initial_states[rain.settings["plant_decay_propagation_speed"].state_topic] == 10
    )

    decay = rain.settings["plant_decay_propagation_speed"]
    decay.matrix = Mock()
    decay.on_message(20)
    assert decay.state_value == pytest.approx(20)
    assert paho.publish.call_args.args == (decay.state_topic, "20.0")

    paho.reset_mock()
    retained_command = MQTTMessage(topic=setting.mqtt_topic.encode())
    retained_command.payload = b"2.8"
    retained_command.retain = True
    callback(paho, None, retained_command)
    assert setting.value == pytest.approx(0.0028)
    assert paho.publish.call_args.args == (setting.state_topic, "2.8")
    callback(paho, None, retained_command)
    assert setting.value == pytest.approx(0.0028)
    assert all(
        call.args == (setting.state_topic, "2.8") for call in paho.publish.call_args_list
    )

    paho.reset_mock()
    mqtt_client._on_connect(paho, None, Mock(), Mock(is_failure=False), None)
    current_states = {
        call.args[0]: loads(call.args[1])
        for call in paho.publish.call_args_list
        if call.args[0].endswith("/state")
    }
    assert current_states[setting.state_topic] == pytest.approx(2.8)


def test_programmatic_updates_publish_current_state(mqtt_client: MqttClient) -> None:
    """Internal setting changes update HA and retain an externally scaled command."""
    contents = tuple(item for item in get_library() if isinstance(item, DynamicContent))
    register_discovery(mqtt_client, contents)
    rain = next(item for item in contents if item.id == "raining-grid")
    setting = rain.settings["plant_growth_chance"]
    rain.update_setting("plant_growth_chance", 0.025)
    paho = cast("Mock", mqtt_client._client)
    assert [
        (call.args[0], loads(call.args[1])) for call in paho.publish.call_args_list
    ] == [(setting.mqtt_topic, 2.5), (setting.state_topic, 2.5)]
