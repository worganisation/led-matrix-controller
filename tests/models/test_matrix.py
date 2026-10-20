"""Tests for matrix content selection."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, cast
from unittest.mock import Mock, patch

import pytest
from content import Clock, Combination, GifViewer, RainingGrid
from content.base import ContentBase, StopType
from models.matrix import ContentQueue, Matrix
from utils import const

if TYPE_CHECKING:
    from models.matrix import ContentParameters
    from utils.mqtt import MqttClient


@pytest.mark.parametrize("dry_run", [False, True])
def test_alert_precedes_queued_combination(
    mqtt_client: MqttClient,
    *,
    dry_run: bool,
) -> None:
    """Select the alert ahead of a combination and preserve the background queue."""
    matrix = Mock(spec=Matrix)
    matrix._attempt_combination.side_effect = partial(Matrix._attempt_combination, matrix)
    matrix._content_queue = ContentQueue(mqtt_client, "/test/content-queue")

    alert = Mock(spec=GifViewer, id="gif-alert-bell", priority=1.0)
    background = Mock(spec=Combination, id="combination", priority=10.0)
    parameters = cast("ContentParameters", {"source": "doorbell"})
    matrix._content_queue.add(background, cast("ContentParameters", {}))
    matrix._content_queue.add(alert, parameters)

    selected, selected_parameters = Matrix._get_next_content(matrix, dry_run=dry_run)

    assert selected is alert
    assert selected_parameters is parameters
    assert matrix._content_queue.qsize() == (2 if dry_run else 1)

    if dry_run:
        selected, _ = Matrix._get_next_content(matrix)
        assert selected is alert

    resumed, _ = Matrix._get_next_content(matrix)
    assert resumed is background
    assert matrix._content_queue.empty()


@pytest.mark.parametrize("clock_priority", [5.0, 15.0])
@pytest.mark.parametrize("alert_timing", ["before", "after", "none"])
def test_running_rain_moves_into_combination_without_teardown(
    mqtt_client: MqttClient,
    clock_priority: float,
    alert_timing: str,
) -> None:
    """Reuse running rain immediately, including when an alert precedes the combination."""
    matrix = Mock(spec=Matrix)
    matrix._attempt_combination.side_effect = partial(Matrix._attempt_combination, matrix)
    matrix._content_works_with.side_effect = partial(Matrix._content_works_with, matrix)
    matrix._get_next_content.side_effect = partial(Matrix._get_next_content, matrix)
    matrix.content_works_with = {RainingGrid: {Clock}, Clock: {RainingGrid}}
    matrix._content_queue = ContentQueue(mqtt_client, "/test/content-queue")

    rain = Mock(spec=RainingGrid, id="raining-grid", priority=10.0, active=True)
    rain.stop.side_effect = partial(ContentBase.stop, rain)
    rain.teardown.side_effect = AssertionError("Rain must not drain before reuse")
    clock = Mock(spec=Clock, id="clock", priority=clock_priority)
    combination = Mock(
        spec=Combination,
        id="combination",
        content=(clock, rain),
        content_ids=("clock", "raining-grid"),
    )
    combination.update_setting.return_value = combination
    matrix._sort_content.return_value = (clock, rain)
    matrix.current_content = rain
    parameters = cast("ContentParameters", {})

    alert = Mock(spec=GifViewer, id="gif-alert-bell", priority=1.0)
    matrix._content = {"clock": clock, "gif-alert-bell": alert}
    if alert_timing == "before":
        matrix._content_queue.add(alert, parameters)

    with patch.object(ContentBase, "get", return_value=combination):
        Matrix._on_content_message(
            matrix,
            {"id": "clock", "priority": clock_priority, "parameters": parameters},
        )

    if alert_timing == "after":
        Matrix._on_content_message(
            matrix,
            {"id": "gif-alert-bell", "priority": 1.0, "parameters": parameters},
        )

    set_content = Mock()
    Matrix._handle_content_stop(matrix, parameters, set_content)

    rain.teardown.assert_not_called()
    set_content.assert_not_called()
    assert rain.priority == pytest.approx(10.0)
    assert not rain.active
    assert combination.priority == min(10.0, clock_priority)
    combination.update_setting.assert_called_once_with(
        "content",
        value=(clock, rain),
        invoke_callback=True,
    )
    alert_queued = alert_timing != "none"
    assert matrix._content_queue.qsize() == (2 if alert_queued else 1)

    if alert_queued:
        selected, _ = Matrix._get_next_content(matrix)
        assert selected is alert

    selected, _ = Matrix._get_next_content(matrix)
    assert selected is combination
    assert rain in selected.content
    assert matrix._content_queue.empty()


@pytest.mark.parametrize("stop_reason", [StopType.CANCEL, StopType.EXPIRED])
def test_stopped_rain_still_runs_teardown(
    mqtt_client: MqttClient,
    stop_reason: StopType,
) -> None:
    """Drain rain when it is actually cancelled or expires."""
    matrix = Mock(spec=Matrix)
    matrix._content_queue = ContentQueue(mqtt_client, "/test/content-queue")
    rain = Mock(spec=RainingGrid, id="raining-grid", priority=10.0, active=True)
    rain.teardown.return_value = iter((None, None))
    matrix.current_content = rain
    set_content = Mock()

    ContentBase.stop(rain, stop_reason)
    Matrix._handle_content_stop(matrix, cast("ContentParameters", {}), set_content)

    rain.teardown.assert_called_once_with()
    assert set_content.call_count == 2
    assert not rain.active
    assert rain.priority == const.MAX_PRIORITY
    assert matrix._content_queue.empty()


def test_alert_interrupts_active_rain_without_teardown(mqtt_client: MqttClient) -> None:
    """Interrupt active rain for a doorbell alert and resume it afterward."""
    matrix = Mock(spec=Matrix)
    matrix._attempt_combination.side_effect = partial(Matrix._attempt_combination, matrix)
    matrix._get_next_content.side_effect = partial(Matrix._get_next_content, matrix)
    matrix._content_queue = ContentQueue(mqtt_client, "/test/content-queue")
    rain = Mock(spec=RainingGrid, id="raining-grid", priority=10.0, active=True)
    rain.stop.side_effect = partial(ContentBase.stop, rain)
    rain.teardown.side_effect = AssertionError("Interrupted rain must not drain")
    matrix.current_content = rain
    alert = Mock(spec=GifViewer, id="gif-alert-bell", priority=1.0)
    matrix._content = {"gif-alert-bell": alert}
    parameters = cast("ContentParameters", {})
    set_content = Mock()

    Matrix._on_content_message(
        matrix,
        {"id": "gif-alert-bell", "priority": 1.0, "parameters": parameters},
    )
    Matrix._handle_content_stop(matrix, parameters, set_content)

    rain.teardown.assert_not_called()
    set_content.assert_not_called()
    assert not rain.active
    assert rain.priority == pytest.approx(10.0)
    selected, _ = Matrix._get_next_content(matrix)
    assert selected is alert
    resumed, _ = Matrix._get_next_content(matrix)
    assert resumed is rain
    assert matrix._content_queue.empty()
