"""Process incoming audio and save coherent FFT frames for the display."""

from __future__ import annotations

import collections
import os
import signal
import threading
import time
from typing import TYPE_CHECKING, Final

import numpy as np
import pyaudio
from scipy.fft import rfft
from utils import const, to_kebab_case
from utils.config import SETTINGS
from utils.helpers import MAX_AUDIO_CHUNK_SIZE, AudioFrameBuffer
from utils.mqtt import MqttClient
from wg_utilities.loggers import get_streaming_logger

if TYPE_CHECKING:
    from numpy.typing import NDArray

LOGGER = get_streaming_logger(__name__)
AV_CONTENT_ID: Final = "audio-visualiser"
COMBO_CONTENT_ID: Final = "combination"
_CONTENT_TOPIC_PREFIX: Final = f"/{to_kebab_case(const.HOSTNAME)}"
CHUNK_SIZE_TOPIC: Final = f"{_CONTENT_TOPIC_PREFIX}/{AV_CONTENT_ID}/parameter/chunk-size"
SAMPLE_RATE_TOPIC: Final = (
    f"{_CONTENT_TOPIC_PREFIX}/{AV_CONTENT_ID}/parameter/sample-rate"
)
CURRENT_CONTENT_TOPIC: Final = f"{_CONTENT_TOPIC_PREFIX}/matrix/current-content"
COMBO_CONTENT_TOPIC: Final = (
    f"{_CONTENT_TOPIC_PREFIX}/{COMBO_CONTENT_ID}/parameter/content"
)
MAX_MAGNITUDE_TOPIC: Final = f"/{const.HOSTNAME}/audio-processor/max-magnitude"
MIN_MAGNITUDE_ABSOLUTE_STEP: Final = 1e-6
MAX_SAMPLE_RATE: Final = 100000
TELEMETRY_INTERVAL: Final = 1.0


class AudioProcessor:
    """Own the audio stream on one worker; MQTT only changes desired state."""

    def __init__(self) -> None:
        self.active = False
        self.chunk_size = 441
        self.sample_rate = 44100
        self.audio_visualiser_in_combination = False
        self.current_content: str | None = None
        self._state_lock = threading.Lock()
        self._shutdown = threading.Event()
        self.worker_thread: threading.Thread | None = None
        self.max_magnitude = MIN_MAGNITUDE_ABSOLUTE_STEP
        self.magnitude_history: collections.deque[float] = collections.deque(
            maxlen=SETTINGS.magnitude_history_size,
        )
        self.last_magnitude_update = time.monotonic()
        self._last_telemetry = 0.0
        self.mqtt = MqttClient(connect=True)
        self.mqtt.add_topic_callback(
            CURRENT_CONTENT_TOPIC,
            self._on_current_content_message,
        )
        self.mqtt.add_topic_callback(
            COMBO_CONTENT_TOPIC,
            self._on_combined_content_message,
        )
        self.mqtt.add_topic_callback(CHUNK_SIZE_TOPIC, self._on_chunk_size_message)
        self.mqtt.add_topic_callback(SAMPLE_RATE_TOPIC, self._on_sample_rate_message)

    def normalise_magnitudes(self, data: NDArray[np.int16]) -> NDArray[np.float64]:
        """Apply the real FFT and keep silent and transient frames finite."""
        magnitudes: NDArray[np.float64] = np.abs(rfft(data))
        current_max = float(magnitudes.max())
        self.magnitude_history.append(current_max)
        previous = self.max_magnitude
        target = (
            float(np.percentile(self.magnitude_history, 95))
            if len(self.magnitude_history) >= SETTINGS.magnitude_history_size / 2
            else max(previous, current_max)
        )
        now = time.monotonic()
        if now - self.last_magnitude_update >= SETTINGS.max_magnitude_update_frequency:
            step = max(
                previous * SETTINGS.max_magnitude_relative_step,
                MIN_MAGNITUDE_ABSOLUTE_STEP,
            )
            self.max_magnitude = max(
                MIN_MAGNITUDE_ABSOLUTE_STEP,
                float(np.clip(target, previous - step, previous + step)),
            )
            self.last_magnitude_update = now

        if now - self._last_telemetry >= TELEMETRY_INTERVAL:
            self.mqtt.publish(
                MAX_MAGNITUDE_TOPIC,
                round(self.max_magnitude, 3),
                retain=True,
            )
            self._last_telemetry = now

        magnitudes /= max(target, MIN_MAGNITUDE_ABSOLUTE_STEP)
        np.clip(magnitudes, 0, 1, out=magnitudes)
        return magnitudes

    def process_incoming_audio(self) -> None:
        """Poll available samples so shutdown and reconfiguration remain responsive."""
        try:
            self._run_stream()
        except Exception:
            LOGGER.exception("Audio processing failed; terminating for service restart")
            os.kill(os.getpid(), signal.SIGTERM)

    def _run_stream(self) -> None:
        audio = pyaudio.PyAudio()
        stream: pyaudio.Stream | None = None
        stream_config: tuple[int, int] | None = None
        frames = AudioFrameBuffer()
        try:
            while not self._shutdown.is_set():
                with self._state_lock:
                    active = self.active
                    config = (self.chunk_size, self.sample_rate)

                if not active or config != stream_config:
                    if stream is not None:
                        stream.close()
                        stream = None
                        stream_config = None

                    if not active:
                        self._shutdown.wait(0.05)
                        continue

                    chunk_size, sample_rate = config
                    stream = audio.open(
                        format=pyaudio.paInt16,
                        channels=1,
                        rate=sample_rate,
                        input=True,
                        frames_per_buffer=chunk_size,
                    )
                    stream_config = config
                    self.magnitude_history.clear()
                    LOGGER.info("Audio stream configured: %s samples at %s Hz", *config)

                if stream is None:
                    continue

                chunk_size, sample_rate = config
                if stream.get_read_available() < chunk_size:
                    self._shutdown.wait(0.01)
                    continue

                samples = np.frombuffer(
                    stream.read(chunk_size, exception_on_overflow=False),
                    dtype=np.int16,
                )
                frames.write(self.normalise_magnitudes(samples), chunk_size, sample_rate)
        finally:
            if stream is not None:
                stream.close()
            audio.terminate()
            frames.close()

    def _on_chunk_size_message(self, value: object) -> None:
        if type(value) is not int or not 1 <= value <= MAX_AUDIO_CHUNK_SIZE:
            LOGGER.warning("Ignoring invalid audio chunk size: %r", value)
            return

        with self._state_lock:
            self.chunk_size = value

    def _on_sample_rate_message(self, value: object) -> None:
        if type(value) is not int or not 1 <= value <= MAX_SAMPLE_RATE:
            LOGGER.warning("Ignoring invalid audio sample rate: %r", value)
            return

        with self._state_lock:
            self.sample_rate = value

    def _on_combined_content_message(self, value: object) -> None:
        if not isinstance(value, list):
            return

        self.audio_visualiser_in_combination = AV_CONTENT_ID in value
        self.update_loop_status()

    def _on_current_content_message(self, value: object) -> None:
        if value is not None and not isinstance(value, str):
            return

        self.current_content = value
        self.update_loop_status()

    def update_loop_status(self) -> None:
        """Update desired playback without joining or modifying the audio stream."""
        with self._state_lock:
            self.active = self.current_content == AV_CONTENT_ID or (
                self.current_content == COMBO_CONTENT_ID
                and self.audio_visualiser_in_combination
            )

    def start(self) -> None:
        """Start the single stream owner."""
        self.worker_thread = threading.Thread(
            target=self.process_incoming_audio,
            name="audio-processor",
            daemon=True,
        )
        self.worker_thread.start()

    def close(self) -> None:
        """Request shutdown without waiting indefinitely for a native audio driver."""
        self._shutdown.set()
        if self.worker_thread is not None:
            self.worker_thread.join(timeout=2)
            if self.worker_thread.is_alive():
                LOGGER.error("Audio driver did not stop within two seconds")


def main() -> None:
    """Run the MQTT subscriber and audio worker."""
    processor = AudioProcessor()
    processor.start()
    try:
        processor.mqtt.loop_forever()
    finally:
        processor.close()


if __name__ == "__main__":
    main()
