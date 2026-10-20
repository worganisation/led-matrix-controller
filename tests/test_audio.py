"""Audio frame transport, spectrum mapping and worker regression tests."""

from __future__ import annotations

import fcntl
import importlib
import sys
import threading
import time
from typing import TYPE_CHECKING
from unittest.mock import Mock

import numpy as np
import pytest
from content.audio_visualiser import AudioVisualiser
from paho.mqtt.client import MQTTMessage
from scipy.fft import rfftfreq
from utils import helpers
from utils.mqtt import MqttClient

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path
    from types import ModuleType


@pytest.fixture
def processor_module(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Replace unavailable audio hardware at its module boundary."""
    monkeypatch.setitem(sys.modules, "pyaudio", Mock())
    sys.modules.pop("audio_processor", None)
    module = importlib.import_module("audio_processor")
    monkeypatch.setattr(module, "MqttClient", Mock())
    return module


@pytest.fixture
def frames(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[helpers.AudioFrameBuffer]:
    """Use an isolated shared frame file."""
    monkeypatch.setattr(helpers, "_AUDIO_FRAME_DIRECTORY", tmp_path)
    frame = helpers.AudioFrameBuffer()
    yield frame
    frame.close()


def test_maximum_chunk_and_reopen(frames: helpers.AudioFrameBuffer) -> None:
    """The maximum configured chunk fits and survives another reader closing."""
    magnitudes = np.linspace(0, 1, 10001)
    frames.write(magnitudes, 20000, 44100)
    second = helpers.AudioFrameBuffer()
    snapshot = np.zeros_like(magnitudes)
    assert second.read(snapshot, 20000, 44100)
    np.testing.assert_array_equal(snapshot, magnitudes)
    second.close()
    assert frames.read(snapshot, 20000, 44100)
    assert not frames.read(snapshot, 20000, 48000)
    assert not frames.read(snapshot[:221], 441, 44100)


def test_busy_frame_does_not_block(frames: helpers.AudioFrameBuffer) -> None:
    """A renderer skips frames while another file descriptor owns the writer lock."""
    second = helpers.AudioFrameBuffer()
    fcntl.flock(second._fd, fcntl.LOCK_EX)
    try:
        assert not frames.read(np.zeros(221), 441, 44100)
    finally:
        fcntl.flock(second._fd, fcntl.LOCK_UN)
        second.close()


def test_stale_frame_is_rejected(
    frames: helpers.AudioFrameBuffer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An exited producer does not leave a permanently lit spectrum."""
    frames.write(np.ones(221), 441, 44100)
    now = time.monotonic()
    monkeypatch.setattr(helpers.time, "monotonic", lambda: now + 2)
    assert not frames.read(np.zeros(221), 441, 44100)


def test_fft_frequency_mapping_and_coincident_foci() -> None:
    """The selected bin is at the cutoff, with finite coincident-foci indices."""
    visualiser = AudioVisualiser(chunk_size=441, sample_rate=44100)
    frequencies = rfftfreq(441, 1 / 44100)
    assert frequencies[visualiser.freq_bin_indices.max()] <= 5000
    assert frequencies[visualiser.freq_bin_indices.max()] > 4800
    visualiser.high_freq_x = visualiser.low_freq_x
    visualiser.high_freq_y = visualiser.low_freq_y
    with np.errstate(divide="raise", invalid="raise"):
        visualiser.update_frequency_foci()
    assert visualiser.freq_bin_indices.min() >= 0


def test_silence_and_transients_remain_finite(processor_module: ModuleType) -> None:
    """A full silence history cannot create NaN frames or overflow the colormap."""
    processor = processor_module.AudioProcessor()
    for _ in range(processor_module.SETTINGS.magnitude_history_size):
        with np.errstate(divide="raise", invalid="raise"):
            result = processor.normalise_magnitudes(np.zeros(441, dtype=np.int16))
        assert not result.any()
    result = processor.normalise_magnitudes(np.full(441, 32767, dtype=np.int16))
    assert np.isfinite(result).all()
    assert result.max() <= 1


def test_callbacks_only_change_desired_state(processor_module: ModuleType) -> None:
    """MQTT callbacks validate configuration without touching the native stream."""
    processor = processor_module.AudioProcessor()
    processor._on_chunk_size_message(20000)
    processor._on_sample_rate_message(48000)
    processor._on_chunk_size_message(20001)
    processor._on_sample_rate_message(value=True)
    assert (processor.chunk_size, processor.sample_rate) == (20000, 48000)
    processor._on_current_content_message("audio-visualiser")
    assert processor.active
    processor._on_current_content_message("clock")
    assert not processor.active
    processor_module.pyaudio.PyAudio.assert_not_called()


def test_worker_stops_without_waiting_for_full_chunk(
    processor_module: ModuleType,
    frames: helpers.AudioFrameBuffer,
) -> None:
    """Even a very slow sampling rate does not make shutdown wait for samples."""
    del frames
    stream: Mock = processor_module.pyaudio.PyAudio.return_value.open.return_value
    stream.get_read_available.return_value = 0
    processor = processor_module.AudioProcessor()
    processor._on_chunk_size_message(20000)
    processor._on_sample_rate_message(1)
    processor._on_current_content_message("audio-visualiser")
    opened = threading.Event()

    def no_samples() -> int:
        opened.set()
        return 0

    stream.get_read_available.side_effect = no_samples
    processor.start()
    assert opened.wait(1)
    processor.close()
    assert not processor.worker_thread.is_alive()
    stream.read.assert_not_called()
    stream.close.assert_called_once()


def test_worker_reconfigures_on_its_own_thread(
    processor_module: ModuleType,
    frames: helpers.AudioFrameBuffer,
) -> None:
    """A retained setting update cannot close a stream from the MQTT thread."""
    del frames
    processor = processor_module.AudioProcessor()
    stream: Mock = processor_module.pyaudio.PyAudio.return_value.open.return_value
    first_poll = threading.Event()
    reconfigured = threading.Event()
    owner_threads: list[int] = []

    def available() -> int:
        first_poll.set()
        return 0

    def open_stream(**kwargs: object) -> Mock:
        owner_threads.append(threading.get_ident())
        if kwargs["frames_per_buffer"] == 1000:
            reconfigured.set()
        return stream

    processor_module.pyaudio.PyAudio.return_value.open.side_effect = open_stream
    stream.get_read_available.side_effect = available
    processor._on_current_content_message("audio-visualiser")
    processor.start()
    try:
        assert first_poll.wait(1)
        processor._on_chunk_size_message(1000)
        assert reconfigured.wait(1)
    finally:
        processor.close()

    assert len(owner_threads) == 2
    assert len(set(owner_threads)) == 1
    assert owner_threads[0] != threading.get_ident()
    assert stream.close.call_count == 2


def test_worker_failure_requests_service_restart(
    processor_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A dead audio worker cannot leave the MQTT process silently healthy."""
    processor = processor_module.AudioProcessor()
    monkeypatch.setattr(
        processor,
        "_run_stream",
        Mock(side_effect=OSError("driver failed")),
    )
    terminate = Mock()
    monkeypatch.setattr(processor_module.os, "kill", terminate)
    processor.process_incoming_audio()
    terminate.assert_called_once_with(
        processor_module.os.getpid(),
        processor_module.signal.SIGTERM,
    )


def test_invalid_frame_shape_cannot_overwrite_transport(
    frames: helpers.AudioFrameBuffer,
) -> None:
    """Malformed producer buffers are rejected before copying into the mapping."""
    with pytest.raises(ValueError, match="length"):
        frames.write(np.zeros(220), 441, 44100)
    with pytest.raises(ValueError, match="capacity"):
        frames.write(np.zeros(10002), 20002, 44100)


def test_interrupted_write_invalidates_frame(
    frames: helpers.AudioFrameBuffer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A producer failure during the copy cannot expose a partially written frame."""
    frames.write(np.ones(221), 441, 44100)
    with monkeypatch.context() as patch:
        patch.setattr(helpers.np, "copyto", Mock(side_effect=OSError("copy interrupted")))
        with pytest.raises(OSError, match="interrupted"):
            frames.write(np.zeros(221), 441, 44100)
    assert not frames.read(np.zeros(221), 441, 44100)


def test_plain_text_current_content_dispatch(
    processor_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dispatch the actual matrix wire format through the real MQTT wrapper."""
    wrapper = object.__new__(MqttClient)
    wrapper._client = Mock()
    wrapper._topics = set()
    monkeypatch.setattr(processor_module, "MqttClient", lambda **_: wrapper)
    processor = processor_module.AudioProcessor()
    callbacks = {
        call.args[0]: call.args[1]
        for call in wrapper._client.message_callback_add.call_args_list
    }

    def dispatch(topic: str, payload: bytes) -> None:
        message = MQTTMessage(topic=topic.encode())
        message.payload = payload
        callbacks[topic](wrapper._client, None, message)

    dispatch(processor_module.CURRENT_CONTENT_TOPIC, b"audio-visualiser")
    assert processor.active
    dispatch(processor_module.CURRENT_CONTENT_TOPIC, b"combination")
    assert not processor.active
    dispatch(processor_module.COMBO_CONTENT_TOPIC, b'["audio-visualiser", "clock"]')
    assert processor.active
    dispatch(processor_module.CURRENT_CONTENT_TOPIC, b"")
    assert processor.current_content is None
    assert not processor.active
    assert processor_module.CURRENT_CONTENT_TOPIC in wrapper._topics
