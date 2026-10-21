"""Expose the content settings through Home Assistant MQTT discovery."""

from __future__ import annotations

from enum import StrEnum
from json import dumps
from typing import TYPE_CHECKING

from content.setting import TransitionableSettingMixin

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from content.dynamic_content import DynamicContent
    from content.setting import S, Setting

    from .mqtt import MqttClient


def _title(value: str) -> str:
    return value.replace("-", " ").replace("_", " ").title()


def discovery_config(setting: Setting[S]) -> tuple[str, dict[str, object]] | None:
    """Describe a supported setting using its existing MQTT and entity identities."""
    payload: dict[str, object] = {}

    if setting.type_ in {int, float}:
        domain = "number"
        transition_rate = (
            setting.transition_rate
            if isinstance(setting, TransitionableSettingMixin)
            else 0.01
        )
        payload.update(
            min=setting.minimum,
            max=setting.maximum,
            mode=setting.display_mode,
            step=1 if setting.type_ is int else max(0.001, transition_rate),
            unit_of_measurement=setting.unit_of_measurement or " ",
        )
    elif issubclass(setting.type_, StrEnum):
        domain = "select"
        payload.update(
            options=[_title(option) for option in setting.type_],
            command_template="{{ slugify(value) | tojson }}",
            value_template="{{ value_json.replace('_', ' ').title() }}",
        )
    elif setting.type_ is bool:
        domain = "switch"
        payload.update(
            payload_on="true",
            payload_off="false",
            state_on="true",
            state_off="false",
        )
    elif setting.type_ is str:
        domain = "text"
        payload.update(
            command_template="{{ value | tojson }}",
            value_template="{{ value_json }}",
        )
    else:
        return None

    unique_id = f"mtrxpi_{setting.instance.id.replace('-', '_')}_{setting.slug}"
    payload.update(
        name=f"{_title(setting.instance.id)}: {_title(setting.slug)}",
        unique_id=unique_id,
        default_entity_id=f"{domain}.{unique_id}",
        device={"identifiers": ["mtrxpi"], "name": "MtrxPi"},
        command_topic=setting.mqtt_topic,
        state_topic=f"{setting.mqtt_topic}/state",
        icon=setting.icon,
        retain=True,
    )

    return f"homeassistant/{domain}/{unique_id}/config", payload


def register_discovery(
    mqtt_client: MqttClient,
    contents: Iterable[DynamicContent],
) -> None:
    """Publish retained discovery on broker connections and Home Assistant births."""
    configs: list[tuple[str, str]] = []
    state_publishers: list[Callable[[], None]] = []
    for content in contents:
        for setting in content.settings.values():
            if config := discovery_config(setting):
                topic, payload = config
                configs.append((topic, dumps(payload)))
                setting.state_topic = f"{setting.mqtt_topic}/state"
                state_publishers.append(setting.publish_state)

    def publish_configs() -> None:
        for topic, payload in configs:
            mqtt_client.publish(topic, payload, qos=1, retain=True)

        for publish_state in state_publishers:
            publish_state()

    def on_home_assistant_status(status: str | None) -> None:
        if status == "online":
            publish_configs()

    mqtt_client.add_connect_callback(publish_configs)
    mqtt_client.add_text_topic_callback("homeassistant/status", on_home_assistant_status)
