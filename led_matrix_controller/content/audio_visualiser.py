"""Windows Media Player? ;_;"""  # ruff:ignore[missing-terminal-punctuation]

from __future__ import annotations

import re
from dataclasses import dataclass, field
from json import dumps
from typing import TYPE_CHECKING, Annotated, Final

import numpy as np
from content.setting import ParameterSetting, TransitionableParameterSetting
from numpy.typing import NDArray  # ruff:ignore[typing-only-third-party-import]
from scipy.fft import rfftfreq
from utils import const, hex_to_rgba
from utils.helpers import MAX_AUDIO_CHUNK_SIZE, AudioFrameBuffer
from wg_utilities.loggers import get_streaming_logger

from .dynamic_content import DynamicContent

if TYPE_CHECKING:
    from collections.abc import Generator


LOGGER = get_streaming_logger(__name__)

HEX_CODE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^#?[0-9A-F]{6}(?:[0-9A-F]{2})?$",
    flags=re.IGNORECASE,
)


@dataclass(kw_only=True, slots=True)
class AudioVisualiser(DynamicContent):
    """Visualise the audio from an incoming mic/aux feed."""

    low_freq_x: Annotated[
        int,
        TransitionableParameterSetting(
            minimum=0,
            maximum=const.MATRIX_WIDTH - 1,
            transition_rate=0.05,
            icon="mdi:star-four-points-circle-outline",
            unit_of_measurement="",
            display_mode="slider",
            invoke_settings_callback=True,
        ),
    ] = 1
    """X coordinate of the lowest frequency in the grid."""

    low_freq_y: Annotated[
        int,
        TransitionableParameterSetting(
            minimum=0,
            maximum=const.MATRIX_HEIGHT - 1,
            transition_rate=0.05,
            icon="mdi:star-four-points-circle-outline",
            unit_of_measurement="",
            display_mode="slider",
            invoke_settings_callback=True,
        ),
    ] = 1
    """Y coordinate of the lowest frequency in the grid."""

    high_freq_x: Annotated[
        int,
        TransitionableParameterSetting(
            minimum=0,
            maximum=const.MATRIX_HEIGHT - 1,
            transition_rate=0.05,
            icon="mdi:star-four-points-circle",
            unit_of_measurement="",
            display_mode="slider",
            invoke_settings_callback=True,
        ),
    ] = const.MATRIX_WIDTH - 1
    """X coordinate of the highest frequency in the grid."""

    high_freq_y: Annotated[
        int,
        TransitionableParameterSetting(
            minimum=0,
            maximum=const.MATRIX_HEIGHT - 1,
            transition_rate=0.05,
            icon="mdi:star-four-points-circle",
            unit_of_measurement="",
            display_mode="slider",
            invoke_settings_callback=True,
        ),
    ] = const.MATRIX_HEIGHT - 1
    """Y coordinate of the highest frequency in the grid."""

    cutoff_frequency: Annotated[
        int,
        ParameterSetting(
            minimum=20,
            maximum=22000,
            icon="mdi:arrow-collapse-up",
            unit_of_measurement="Hz",
            display_mode="slider",
            invoke_settings_callback=True,
        ),
    ] = 5000

    colormap_length: Annotated[
        int,
        ParameterSetting(
            minimum=100,
            maximum=10000,
            icon="mdi:palette",
            unit_of_measurement="colors",
            display_mode="box",
            invoke_settings_callback=True,
        ),
    ] = 10000

    low_magnitude_hex_color: Annotated[
        str,
        ParameterSetting(
            invoke_settings_callback=True,
            icon="mdi:palette",
            validator=HEX_CODE_PATTERN.fullmatch,
        ),
    ] = "#0000FF80"

    high_magnitude_hex_color: Annotated[
        str,
        ParameterSetting(
            invoke_settings_callback=True,
            icon="mdi:palette",
            validator=HEX_CODE_PATTERN.fullmatch,
        ),
    ] = "#FF0000FF"

    _frequency_mapping: tuple[int, int, NDArray[np.int_]] = field(init=False, repr=False)

    @property
    def freq_bin_indices(self) -> NDArray[np.int_]:
        """Frequency indices for the current complete mapping."""
        return self._frequency_mapping[2]

    sample_rate: Annotated[
        int,
        ParameterSetting(
            minimum=1,
            maximum=100000,
            invoke_settings_callback=True,
            icon="mdi:sine-wave",
            unit_of_measurement="Hz",
        ),
    ] = 44100
    """Number of audio samples per second."""

    chunk_size: Annotated[
        int,
        ParameterSetting(
            minimum=1,
            maximum=MAX_AUDIO_CHUNK_SIZE,
            invoke_settings_callback=True,
            icon="mdi:table-split-cell",
            unit_of_measurement="",
        ),
    ] = 441
    """Number of audio samples per chunk.

    Set to 441 to allow for 100 FPS updates.
    """

    def __post_init__(self) -> None:
        """Initialize the audio visualiser."""
        DynamicContent.__post_init__(self)

        self.update_colormap()
        self.update_frequency_foci()

    def refresh_content(self) -> Generator[None, None, None]:
        """Continuously updates the visualizer's pixel grid with audio frequency magnitudes.

        While active, reads audio data from shared memory, maps magnitudes to colormap indices,
        and updates the display grid based on frequency bin mappings. Yields control after each update
        to allow asynchronous operation.
        """
        frames = AudioFrameBuffer()
        audio = np.empty(0, dtype=np.float64)
        try:
            while self.active:
                chunk_size, sample_rate, indices = self._frequency_mapping
                if audio.size != chunk_size // 2 + 1:
                    audio = np.zeros(chunk_size // 2 + 1, dtype=np.float64)

                if not frames.read(audio, chunk_size, sample_rate):
                    audio.fill(0)

                audio_ints = np.clip(
                    audio * self.colormap_length,
                    0,
                    len(self.colormap) - 1,
                ).astype(np.int_)
                self.pixels[:, :] = audio_ints[indices]
                yield
        finally:
            frames.close()

    def setting_update_callback(self, update_setting: str | None = None) -> None:
        """Update the colormap."""
        if update_setting in {
            "low_magnitude_hex_color",
            "high_magnitude_hex_color",
            "colormap_length",
        }:
            self.update_colormap()
        elif update_setting in {
            "low_freq_x",
            "low_freq_y",
            "high_freq_x",
            "high_freq_y",
            "cutoff_frequency",
            "sample_rate",
            "chunk_size",
        }:
            self.update_frequency_foci()

    def update_colormap(self) -> None:
        """Update the colormap."""
        low_magnitude_color = hex_to_rgba(self.low_magnitude_hex_color)
        high_magnitude_color = hex_to_rgba(self.high_magnitude_hex_color)

        colors = {
            0: (0, 0, 0, 0),
            self.colormap_length // 150: (0, 0, 0, 0),
            self.colormap_length // 80: low_magnitude_color,
            self.colormap_length // 50: low_magnitude_color,
            self.colormap_length // 10: high_magnitude_color,
            self.colormap_length: high_magnitude_color,
        }

        LOGGER.debug("Colormap: %s", dumps(colors))

        gradient = []
        prev = None
        for index, color in colors.items():
            if prev is None:
                prev = (index, color)
                gradient.append(color)
                continue

            prev_index, prev_color = prev

            if (steps := index - prev_index) > 1:
                for i in range(steps):
                    r = int(prev_color[0] + (color[0] - prev_color[0]) * i / (steps - 1))
                    g = int(prev_color[1] + (color[1] - prev_color[1]) * i / (steps - 1))
                    b = int(prev_color[2] + (color[2] - prev_color[2]) * i / (steps - 1))
                    a = int(prev_color[3] + (color[3] - prev_color[3]) * i / (steps - 1))
                    gradient.append((r, g, b, a))

            prev = (index, color)

        self.colormap = np.array(gradient, dtype=np.uint8)

    def update_frequency_foci(self) -> None:
        """Update the location of the frequency foci on the visualisation."""
        x, y = np.meshgrid(np.arange(self.width), np.arange(self.height))

        # Compute distances from the lowest/highest frequency focal points
        dist_low = np.sqrt((x - self.high_freq_x) ** 2 + (y - self.high_freq_y) ** 2)
        dist_high = np.sqrt((x - self.low_freq_x) ** 2 + (y - self.low_freq_y) ** 2)

        # Combine distances to create a gradient
        total_distance = dist_low + dist_high

        # Normalize distances to range [0, 1]
        normalized_distances = np.divide(
            dist_high,
            total_distance,
            out=np.zeros_like(total_distance),
            where=total_distance != 0,
        )

        chunk_size, sample_rate = self.chunk_size, self.sample_rate
        freqs = rfftfreq(chunk_size, 1 / sample_rate)
        cutoff_idx = min(
            np.where(freqs <= self.cutoff_frequency)[0][-1],
            chunk_size // 2,
        )

        # Map normalized distances to frequency bin indices
        freq_bin_indices = (normalized_distances * cutoff_idx).astype(int)

        # Ensure indices are within valid range
        self._frequency_mapping = (
            chunk_size,
            sample_rate,
            np.clip(freq_bin_indices, 0, cutoff_idx),
        )
