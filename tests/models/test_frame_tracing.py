"""Render-path integration with the OpenTelemetry SDK and a simulated panel."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import Mock, patch

import numpy as np
import pytest
from models.matrix import Matrix
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

if TYPE_CHECKING:
    from utils.mqtt import MqttClient


def test_sampled_render_and_idle_clear(mqtt_client: MqttClient) -> None:
    """Exercise sampling, the hardware boundaries and a failed clear.

    Args:
        mqtt_client: Isolated controller MQTT client.
    """
    exporter = InMemorySpanExporter()
    provider = TracerProvider(shutdown_on_exit=False)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    driver = Mock(width=64, height=64)
    with patch("models.matrix.mtrx.RGBMatrix", return_value=driver):
        matrix = Matrix(
            mqtt_client=mqtt_client,
            content_works_with={},
            tracer=provider.get_tracer("test"),
        )

    content = Mock(id="clock", priority=15.0, width=1, height=1, position=(0, 0))
    content.get_content.return_value = np.zeros((1, 1, 4), dtype=np.uint8)
    matrix._current_content = content
    matrix.set_image_swap_canvas()
    matrix.set_image_swap_canvas()

    matrix._next_frame_trace = 0
    content.get_content.return_value = Mock()
    matrix.get_canvas_swap_canvas()
    driver.SwapOnVSync.side_effect = RuntimeError("panel unavailable")
    with pytest.raises(RuntimeError, match="panel unavailable"):
        matrix.clear_matrix()

    dynamic, prepared, blank = exporter.get_finished_spans()
    assert [event.name for event in dynamic.events] == [
        "image.prepared",
        "canvas.uploaded",
        "vsync.complete",
    ]
    assert [event.name for event in prepared.events] == [
        "canvas.selected",
        "vsync.complete",
    ]
    assert [event.name for event in blank.events] == ["canvas.cleared"]
    assert blank.status.status_code == StatusCode.ERROR
    assert blank.attributes
    assert blank.attributes["error.type"] == "RuntimeError"
    driver.SwapOnVSync.side_effect = None
