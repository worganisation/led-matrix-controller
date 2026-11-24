"""Eagerly validated configuration shared by both controller processes."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from socket import gethostname
from sys import platform
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application environment variables, validated before content is constructed."""

    model_config = SettingsConfigDict(
        extra="ignore",
        allow_inf_nan=False,
        hide_input_in_errors=True,
    )

    mqtt_username: Annotated[str, Field(min_length=1)]
    mqtt_password: Annotated[str, Field(min_length=1, repr=False)]
    mqtt_host: Annotated[str, Field(min_length=1)] = "homeassistant.local"
    hostname_override: Annotated[str, Field(min_length=1)] = re.sub(
        r"[^a-z0-9]",
        "-",
        gethostname().lower(),
    )
    debug_mode: bool = False
    rng_seed: Annotated[int, Field(ge=0)] = Field(
        default_factory=lambda: int(datetime.now(UTC).timestamp()),
    )
    ticks_per_second: Annotated[int, Field(gt=0)] = 100
    audio_visualiser_shm_name: Annotated[str, Field(min_length=1)]
    automaton_queue_size: Annotated[int, Field(gt=0)] = 100
    magnitude_history_size: Annotated[int, Field(gt=0)] = 200
    max_magnitude_relative_step: Annotated[float, Field(gt=0)] = 0.01
    max_magnitude_update_frequency: Annotated[float, Field(gt=0)] = 0.01
    artwork_dir: Path = (
        (
            Path("/var/cache")
            if gethostname().lower() == "mtrxpi" and platform != "darwin"
            else Path.home()
        )
        / "led-matrix-controller"
        / "artwork"
    )

    @field_validator("mqtt_host")
    @classmethod
    def validate_mqtt_host(cls, value: str) -> str:
        """Paho expects a hostname, without a URL scheme or path."""
        if "://" in value or "/" in value or any(char.isspace() for char in value):
            raise ValueError("MQTT_HOST must be a hostname or IP address")

        return value


SETTINGS = Settings()
