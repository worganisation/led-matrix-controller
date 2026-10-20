"""Settings transition and callback regression tests."""

from __future__ import annotations

from threading import Condition
from typing import cast
from unittest.mock import Mock, patch

import pytest
from content.dynamic_content import DynamicContent
from content.setting import ParameterSetting, TransitionableParameterSetting


def make_setting() -> TransitionableParameterSetting[float]:
    """Build a setting without rendering or opening MQTT connections."""
    setting = TransitionableParameterSetting[float](
        icon="",
        unit_of_measurement="",
        transition_rate=0.25,
    )
    setting.setup(
        field_name="level",
        instance=Mock(level=0.0, active=True),
        type_=float,
    )
    setting.matrix = Mock(tick_condition=Condition(), publish_attributes=Mock())
    return setting


def test_transition_completes_without_render_ticks() -> None:
    """An idle or sleeping renderer cannot leave a transition waiting forever."""
    setting = make_setting()
    setting._set_value_from_payload(1.0)
    setting.transition_thread.join(timeout=1)

    assert not setting.transition_thread.is_alive()
    assert setting.value == pytest.approx(1.0)
    assert not setting._transition_running


def test_new_target_replaces_transition_and_inactive_content_finishes() -> None:
    """A direct update invalidates the previous worker's target."""
    setting = make_setting()
    setting._set_value_from_payload(100.0)
    cast("Mock", setting.instance).active = False
    setting._set_value_from_payload(0.5)
    setting.transition_thread.join(timeout=1)

    assert not setting.transition_thread.is_alive()
    assert setting.value == pytest.approx(0.5)
    assert setting.target_value == pytest.approx(0.5)


def test_callback_runs_once_for_explicit_update() -> None:
    """Explicit callback requests do not duplicate the setting's own callback."""
    content = Mock(id="content")
    content.level = 0.0
    setting = ParameterSetting[float](
        icon="",
        unit_of_measurement="",
        invoke_settings_callback=True,
    )
    setting.setup(field_name="level", instance=content, type_=float)
    content.settings = {"level": setting}

    with patch.object(ParameterSetting, "_MQTT_CLIENT", Mock(), create=True):
        DynamicContent.update_setting(content, "level", 0.5, invoke_callback=True)

    content.setting_update_callback.assert_called_once_with(update_setting="level")


def test_setting_metadata_does_not_construct_mqtt() -> None:
    """Creating annotations is safe for metadata tooling."""
    with patch("content.setting.MqttClient") as client:
        ParameterSetting[float](icon="")

    client.assert_not_called()
