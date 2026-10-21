"""Exercise interrupted combinations with real child iterators."""

from __future__ import annotations

from functools import partial
from threading import RLock
from typing import TYPE_CHECKING, cast
from unittest.mock import Mock

from content import Clock, Combination, GifViewer, RainingGrid, base
from content.base import StopType
from models.matrix import ContentQueue, Matrix

if TYPE_CHECKING:
    import pytest
    from models.matrix import ContentParameters
    from utils.mqtt import MqttClient


def test_clock_and_rain_resume_after_alert(
    monkeypatch: pytest.MonkeyPatch,
    mqtt_client: MqttClient,
) -> None:
    """Both requested backgrounds resume after their real generators are interrupted."""
    monkeypatch.setattr(base, "_CONTENT_STORE", {})
    rain = RainingGrid(priority=10)
    clock = Clock(priority=15)
    combination = Combination(content=(clock, rain), priority=10)

    matrix = Mock(spec=Matrix)
    matrix._content_lock = RLock()
    matrix.COMBINATION_OVERRIDES = Matrix.COMBINATION_OVERRIDES
    matrix._content_queue = ContentQueue(mqtt_client, "/test/queue")
    matrix.content_works_with = {RainingGrid: {Clock}, Clock: {RainingGrid}}
    for method in (
        "_attempt_combination",
        "_content_works_with",
        "_sort_content",
        "_interrupt_for_queued_content",
    ):
        getattr(matrix, method).side_effect = partial(getattr(Matrix, method), matrix)

    matrix.current_content = combination
    alert = Mock(spec=GifViewer, id="alert", priority=1, stop_reason=None)
    matrix._content = {"alert": alert}
    parameters = cast("ContentParameters", {})
    frames = iter(combination)
    resumed_frames = None

    try:
        next(frames)
        rain_frame_before_alert = rain.frame_index
        Matrix._queue_content_message(
            matrix,
            {"id": "alert", "priority": 1, "parameters": parameters},
        )
        assert combination.stop_reason is StopType.PRIORITY

        frames.close()
        Matrix._handle_content_stop(matrix, parameters, Mock())
        assert Matrix._get_next_content(matrix)[0] is alert

        resumed, _ = Matrix._get_next_content(matrix)
        assert resumed is combination
        assert isinstance(resumed, Combination)
        resumed.stop_reason = None
        resumed_frames = iter(resumed)
        next(resumed_frames)

        assert resumed.content_ids == ("clock", "raining-grid")
        assert clock.active
        assert rain.active
        assert clock.pixels.any()
        assert rain.frame_index > rain_frame_before_alert
        assert clock.priority == 15
        assert rain.priority == 10
    finally:
        frames.close()
        if resumed_frames is not None:
            resumed_frames.close()

        rain._stop_rules_thread()
