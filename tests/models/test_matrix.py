"""Tests for matrix content selection."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, cast
from unittest.mock import Mock

import pytest
from content import Combination, GifViewer
from models.matrix import ContentQueue, Matrix

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
