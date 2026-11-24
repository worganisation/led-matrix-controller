"""Validation of complete application configuration."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from utils.config import Settings


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("TICKS_PER_SECOND", "0"),
        ("AUTOMATON_QUEUE_SIZE", "0"),
        ("MAGNITUDE_HISTORY_SIZE", "-1"),
        ("MAX_MAGNITUDE_RELATIVE_STEP", "nan"),
        ("MAX_MAGNITUDE_UPDATE_FREQUENCY", "0"),
        ("MQTT_HOST", "http://homeassistant.local"),
    ],
)
def test_invalid_configuration_fails_eagerly(
    monkeypatch: pytest.MonkeyPatch,
    variable: str,
    value: str,
) -> None:
    """Even settings for an inactive source must be valid at startup."""
    monkeypatch.setenv(variable, value)

    with pytest.raises(ValidationError):
        Settings()
