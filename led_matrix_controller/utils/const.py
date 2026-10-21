"""Constant values."""

from __future__ import annotations

from pathlib import Path
from socket import gethostname
from sys import platform
from typing import Any, Final

import numpy as np
from PIL import Image

from .config import SETTINGS

DEBUG_MODE: Final[bool] = SETTINGS.debug_mode

MQTT_USERNAME: Final[str] = SETTINGS.mqtt_username
MQTT_PASSWORD: Final[str] = SETTINGS.mqtt_password
MQTT_HOST: Final[str] = SETTINGS.mqtt_host
HOSTNAME: Final[str] = SETTINGS.hostname_override

IS_PI = gethostname().lower() == "mtrxpi" and platform != "darwin"

FONT_WIDTH: Final[int] = 5
FONT_HEIGHT: Final[int] = 7
SCROLL_INCREMENT_DISTANCE: Final[int] = 2 * FONT_WIDTH

BOOLEANS: Final[np.typing.NDArray[np.bool_]] = np.array([False, True], dtype=np.bool_)
RNG = np.random.default_rng(SETTINGS.rng_seed)

REPO_PATH: Final[Path] = Path(__file__).parents[2]
ASSETS_DIRECTORY: Final[Path] = REPO_PATH / "assets"

TICKS_PER_SECOND: Final[int] = SETTINGS.ticks_per_second  # ticks
TICK_LENGTH: Final[float] = 1 / TICKS_PER_SECOND  # seconds

MATRIX_HEIGHT: Final[int] = 64
MATRIX_WIDTH: Final[int] = 64

MATRIX_SHAPE: Final[tuple[int, int]] = (MATRIX_HEIGHT, MATRIX_WIDTH)

EMPTY_IMAGE: Final[Image.Image] = Image.new("RGB", MATRIX_SHAPE, (0, 0, 0))

MAX_PRIORITY: Final[float] = 1e10


AUDIO_VISUALISER_SHM_NAME: Final[str] = SETTINGS.audio_visualiser_shm_name


def seconds_to_ticks(seconds: float, *_: Any) -> int:
    """Convert seconds to ticks."""
    return int(seconds * TICKS_PER_SECOND)


def ticks_to_seconds(ticks: int) -> float:
    """Convert ticks to seconds."""
    return ticks * TICK_LENGTH
