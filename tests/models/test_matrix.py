"""Tests for matrix content selection."""

from __future__ import annotations

from functools import partial
from queue import Empty
from signal import SIGTERM
from threading import Event, RLock, Thread
from typing import TYPE_CHECKING, cast
from unittest.mock import Mock, patch

import pytest
from content import Clock, Combination, GifViewer, RainingGrid
from content.base import ContentBase, StopType
from models.matrix import ContentQueue, Matrix
from utils import const

if TYPE_CHECKING:
    from collections.abc import Iterator

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
    matrix._content_lock = RLock()
    matrix._interrupt_for_queued_content.side_effect = partial(
        Matrix._interrupt_for_queued_content,
        matrix,
    )
    matrix._queue_content_message.side_effect = partial(
        Matrix._queue_content_message,
        matrix,
    )
    matrix._attempt_combination.side_effect = partial(Matrix._attempt_combination, matrix)
    matrix._content_queue = ContentQueue(mqtt_client, "/test/content-queue")

    alert = Mock(spec=GifViewer, id="gif-alert-bell", priority=1.0)
    background = Mock(
        spec=Combination,
        id="combination",
        priority=10.0,
        content=(
            Mock(spec=Clock, priority=15.0, stop_reason=None),
            Mock(spec=RainingGrid, priority=10.0, stop_reason=None),
        ),
    )
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
    matrix._content_lock = RLock()
    matrix._interrupt_for_queued_content.side_effect = partial(
        Matrix._interrupt_for_queued_content,
        matrix,
    )
    matrix._queue_content_message.side_effect = partial(
        Matrix._queue_content_message,
        matrix,
    )
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
    combination.content = ()

    def update_combination(
        *_: object,
        value: tuple[Clock, RainingGrid],
        **__: object,
    ) -> Combination:
        combination.content = value
        return combination

    combination.update_setting.side_effect = update_combination
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
    assert isinstance(selected, Combination)
    assert rain in selected.content
    assert matrix._content_queue.empty()


@pytest.mark.parametrize("stop_reason", [StopType.CANCEL, StopType.EXPIRED])
def test_stopped_rain_still_runs_teardown(
    mqtt_client: MqttClient,
    stop_reason: StopType,
) -> None:
    """Drain rain when it is actually cancelled or expires."""
    matrix = Mock(spec=Matrix)
    matrix._content_lock = RLock()
    matrix._interrupt_for_queued_content.side_effect = partial(
        Matrix._interrupt_for_queued_content,
        matrix,
    )
    matrix._queue_content_message.side_effect = partial(
        Matrix._queue_content_message,
        matrix,
    )
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
    matrix._content_lock = RLock()
    matrix._interrupt_for_queued_content.side_effect = partial(
        Matrix._interrupt_for_queued_content,
        matrix,
    )
    matrix._queue_content_message.side_effect = partial(
        Matrix._queue_content_message,
        matrix,
    )
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


def test_queue_removal_preserves_priority_order(mqtt_client: MqttClient) -> None:
    """Removing the heap root cannot move a later request ahead of an earlier one."""
    queue = ContentQueue(mqtt_client, "/test/queue")
    contents = [
        Mock(spec=GifViewer, id=str(priority), priority=float(priority))
        for priority in (1, 5, 2, 6, 7, 3, 4)
    ]
    parameters = cast("ContentParameters", {})
    for content in contents:
        queue.add(content, parameters)

    queue.remove(contents[0], parameters)

    assert [queue.get()[0] for _ in range(queue.qsize())] == [2, 3, 4, 5, 6, 7]


def test_tied_priorities_are_fifo_and_all_visible(mqtt_client: MqttClient) -> None:
    """Unorderable content objects can share a priority without losing telemetry."""
    queue = ContentQueue(mqtt_client, "/test/queue")
    first = Mock(spec=GifViewer, id="first", priority=1.0)
    second = Mock(spec=GifViewer, id="second", priority=1.0)
    parameters = cast("ContentParameters", {})
    queue.add(first, parameters)
    queue.add(second, parameters)

    assert queue.mqtt_attributes == {
        "1.000": {"id": "first", "parameters": parameters},
        "1.000:2": {"id": "second", "parameters": parameters},
    }
    cast("Mock", mqtt_client.publish).assert_called_with(
        topic="/test/queue/state",
        payload=2,
        retain=True,
    )
    assert queue.get()[1] is first
    assert queue.get()[1] is second


def test_queue_replaces_a_reprioritized_request(mqtt_client: MqttClient) -> None:
    """Reprioritizing a queued singleton updates its key and parameters once."""
    queue = ContentQueue(mqtt_client, "/test/queue")
    content = Mock(spec=GifViewer, id="alert", priority=10.0)
    other = Mock(spec=GifViewer, id="other", priority=5.0)
    parameters = cast("ContentParameters", {})
    replacement = cast("ContentParameters", {"source": "new"})
    queue.add(content, parameters)
    queue.add(other, parameters)
    snapshot = iter(queue)
    content.priority = 1.0

    assert "10.000" in queue.mqtt_attributes
    queue.add(content, replacement)

    assert list(snapshot) == [(5.0, other, parameters), (10.0, content, parameters)]
    assert queue.qsize() == 2
    assert queue.get() == (1.0, content, replacement)
    assert queue.get()[1] is other


def test_preview_does_not_combine_or_mutate(mqtt_client: MqttClient) -> None:
    """Previewing compatible content leaves both instances and the queue untouched."""
    matrix = Mock(spec=Matrix)
    matrix._content_queue = ContentQueue(mqtt_client, "/test/queue")
    rain = Mock(spec=RainingGrid, id="rain", priority=10.0, active=True)
    clock = Mock(spec=Clock, id="clock", priority=15.0, active=True)
    parameters = cast("ContentParameters", {})
    matrix._content_queue.add(rain, parameters)
    matrix._content_queue.add(clock, parameters)

    assert Matrix._get_next_content(matrix, dry_run=True) == (rain, parameters)
    matrix._attempt_combination.assert_not_called()
    assert matrix._content_queue.qsize() == 2
    rain.stop.assert_not_called()
    clock.stop.assert_not_called()


def test_interrupted_content_can_resume_an_empty_queue(mqtt_client: MqttClient) -> None:
    """An interruption whose request was withdrawn still resumes the background."""
    matrix = Mock(spec=Matrix)
    matrix._content_lock = RLock()
    matrix._interrupt_for_queued_content.side_effect = partial(
        Matrix._interrupt_for_queued_content,
        matrix,
    )
    matrix._content_queue = ContentQueue(mqtt_client, "/test/queue")
    rain = Mock(
        spec=RainingGrid,
        id="rain",
        priority=10.0,
        active=False,
        stop_reason=StopType.PRIORITY,
    )
    matrix.current_content = rain
    parameters = cast("ContentParameters", {})

    Matrix._handle_content_stop(matrix, parameters, Mock())

    assert matrix._content_queue.get() == (10.0, rain, parameters)
    rain.teardown.assert_not_called()


def test_zero_priority_is_a_valid_request(mqtt_client: MqttClient) -> None:
    """Priority zero queues an alert; only null requests cancellation."""
    matrix = Mock(spec=Matrix)
    matrix._content_queue = ContentQueue(mqtt_client, "/test/queue")
    matrix.current_content = None
    alert = Mock(spec=GifViewer, id="alert", priority=10.0)
    matrix._content = {"alert": alert}
    parameters = cast("ContentParameters", {})

    Matrix._queue_content_message(
        matrix,
        {"id": "alert", "priority": 0, "parameters": parameters},
    )

    assert matrix._content_queue.get() == (0.0, alert, parameters)
    matrix._remove_content.assert_not_called()


def test_render_failure_terminates_the_service() -> None:
    """A dead rendering worker cannot leave the service falsely healthy."""
    matrix = Mock(spec=Matrix)
    matrix._run_content_loop.side_effect = RuntimeError("renderer failed")
    with (
        patch("models.matrix.kill") as terminate,
        patch("models.matrix.getpid", return_value=123),
    ):
        Matrix._content_loop(matrix)

    terminate.assert_called_once_with(123, SIGTERM)


def test_setup_cancellation_does_not_reactivate_content(mqtt_client: MqttClient) -> None:
    """A stop during setup must not enter an iterator that activates playback."""
    matrix = Mock(spec=Matrix)
    matrix._content_lock = RLock()
    matrix._interrupt_for_queued_content.side_effect = partial(
        Matrix._interrupt_for_queued_content,
        matrix,
    )
    matrix._content_queue = ContentQueue(mqtt_client, "/test/queue")
    content = Mock(spec=GifViewer, id="alert", priority=1.0, active=True)
    parameters = cast("ContentParameters", {})
    matrix._content_queue.add(content, parameters)
    matrix._get_next_content.side_effect = partial(Matrix._get_next_content, matrix)
    matrix._render_content.side_effect = partial(Matrix._render_content, matrix)

    def cancel_setup() -> Iterator[None]:
        content.active = False
        yield

    content.setup.side_effect = cancel_setup

    Matrix._run_content_loop(matrix)

    matrix.get_canvas_swap_canvas.assert_not_called()
    matrix._handle_content_stop.assert_called_once()
    assert matrix._content_thread is None


def test_cancel_child_in_a_queued_combination(mqtt_client: MqttClient) -> None:
    """Cancelling rain behind an alert cannot restart it from a queued combination."""
    matrix = Mock(spec=Matrix)
    matrix._content_queue = ContentQueue(mqtt_client, "/test/queue")
    matrix.current_content = Mock(spec=GifViewer)
    rain = Mock(spec=RainingGrid, id="rain", priority=const.MAX_PRIORITY)
    clock = Mock(spec=Clock, id="clock", priority=15.0)
    combination = Mock(
        spec=Combination,
        id="combination",
        priority=10.0,
        content=(rain, clock),
    )
    parameters = cast("ContentParameters", {})
    matrix._content_queue.add(combination, parameters)

    Matrix._remove_content(matrix, rain)

    assert matrix._content_queue.get() == (15.0, clock, parameters)
    assert matrix._content_queue.empty()


def test_surviving_combination_child_resumes_after_worker_closes(
    mqtt_client: MqttClient,
) -> None:
    """Worker cleanup must not discard a still-requested combination member."""
    matrix = Mock(spec=Matrix)
    matrix._content_lock = RLock()
    matrix._content_queue = ContentQueue(mqtt_client, "/test/queue")
    rain = Mock(
        spec=RainingGrid,
        id="rain",
        priority=10.0,
        active=False,
        stop_reason=None,
    )
    matrix.current_content = Mock(
        spec=Combination,
        priority=const.MAX_PRIORITY,
        stop_reason=StopType.TRANSFORM_REQUIRED,
        content=(rain,),
    )
    parameters = cast("ContentParameters", {})

    Matrix._handle_content_stop(matrix, parameters, Mock())

    assert matrix._content_queue.get()[1] is rain


def test_reprioritizing_current_content_yields_to_waiting_alert(
    mqtt_client: MqttClient,
) -> None:
    """Lowering the active item's importance must reconsider the already waiting queue."""
    matrix = Mock(spec=Matrix)
    matrix._interrupt_for_queued_content.side_effect = partial(
        Matrix._interrupt_for_queued_content,
        matrix,
    )
    matrix._content_queue = ContentQueue(mqtt_client, "/test/queue")
    current = Mock(spec=GifViewer, id="current", priority=1.0, stop_reason=None)
    alert = Mock(spec=GifViewer, id="alert", priority=5.0)
    matrix.current_content = current
    matrix._content = {"current": current}
    parameters = cast("ContentParameters", {})
    matrix._content_queue.add(alert, parameters)

    Matrix._queue_content_message(
        matrix,
        {"id": "current", "priority": 10, "parameters": parameters},
    )

    current.stop.assert_called_once_with(StopType.PRIORITY, reset_priority=False)


def test_enqueue_during_worker_exit_starts_a_replacement(mqtt_client: MqttClient) -> None:
    """A producer waiting for shutdown cannot mistake the exiting worker for an owner."""
    matrix = Mock(spec=Matrix)
    matrix._content_lock = RLock()
    matrix._content_queue = ContentQueue(mqtt_client, "/test/queue")
    clearing = Event()
    allow_exit = Event()
    producer_entered = Event()
    producer_finished = Event()
    content = Mock(spec=GifViewer, id="alert", priority=1.0)

    def clear() -> None:
        clearing.set()
        assert allow_exit.wait(2)

    def enqueue() -> None:
        producer_entered.set()
        with matrix._content_lock:
            matrix._content_queue.add(content, cast("ContentParameters", {}))
            Matrix._start_content_thread(matrix)
        producer_finished.set()

    matrix.clear_matrix.side_effect = clear
    worker = Thread(target=partial(Matrix._run_content_loop, matrix))
    producer = Thread(target=enqueue)
    matrix._content_thread = worker
    with patch("models.matrix.Thread") as replacement:
        try:
            worker.start()
            assert clearing.wait(2)
            producer.start()
            assert producer_entered.wait(2)
            assert not producer_finished.is_set()
        finally:
            allow_exit.set()
            worker.join(2)
            if producer.ident is not None:
                producer.join(2)

        assert not worker.is_alive()
        assert not producer.is_alive()
        assert producer_finished.is_set()
        replacement.return_value.start.assert_called_once()
        assert matrix._content_thread is replacement.return_value
        assert matrix._content_queue.get()[1] is content


@pytest.mark.parametrize("priority", [float("inf"), float("-inf"), float("nan")])
def test_nonfinite_priority_is_rejected(mqtt_client: MqttClient, priority: float) -> None:
    """Invalid numeric priorities cannot corrupt queue ordering or cancel content."""
    matrix = Mock(spec=Matrix)
    matrix._content_queue = ContentQueue(mqtt_client, "/test/queue")
    alert = Mock(spec=GifViewer, id="alert", priority=1.0)
    matrix._content = {"alert": alert}

    with pytest.raises(ValueError, match="finite"):
        Matrix._queue_content_message(
            matrix,
            {
                "id": "alert",
                "priority": priority,
                "parameters": cast("ContentParameters", {}),
            },
        )

    assert alert.priority == pytest.approx(1.0)
    assert matrix._content_queue.empty()


def test_existing_combination_reprioritizes_without_duplicate_members() -> None:
    """Updating an existing member changes its combination priority without rebuilding it."""
    matrix = Mock(spec=Matrix)
    matrix.content_works_with = {RainingGrid: {Clock}, Clock: {RainingGrid}}
    matrix._content_works_with.side_effect = partial(Matrix._content_works_with, matrix)
    rain = Mock(spec=RainingGrid, id="rain", priority=10.0)
    clock = Mock(spec=Clock, id="clock", priority=0.0)
    combination = Mock(spec=Combination, content=(clock, rain), priority=10.0)
    matrix._sort_content.return_value = (clock, rain)

    result = Matrix._attempt_combination(matrix, clock, combination)

    assert result is combination
    assert combination.priority == pytest.approx(0.0)
    combination.update_setting.assert_not_called()


def test_render_progress_is_published_only_after_a_frame() -> None:
    """Report render freshness without publishing at the display frame rate."""
    matrix = Mock(spec=Matrix)
    matrix.tick = 0
    matrix._last_progress_publish = 0.0
    matrix.PROGRESS_PUBLISH_INTERVAL = Matrix.PROGRESS_PUBLISH_INTERVAL
    matrix.tick_condition = Mock()
    matrix.tick_condition.acquire.return_value = True
    matrix.canvas = Mock()
    matrix.matrix = Mock()
    matrix.mqtt_client = Mock()
    matrix.mqtt_topic.return_value = "/test/matrix/render-progress"

    with patch("models.matrix.monotonic", side_effect=[10.0, 10.1, 15.0]):
        Matrix.swap_canvas(matrix)
        Matrix.swap_canvas(matrix)
        Matrix.swap_canvas(matrix)

    assert matrix.tick == 3
    assert matrix.mqtt_client.publish.call_count == 2
    assert '"frame": 3' in matrix.mqtt_client.publish.call_args.kwargs["payload"]


def test_alert_during_cancelled_child_teardown_resumes_only_requested_children(
    mqtt_client: MqttClient,
) -> None:
    """Interrupting a draining child cannot put that cancelled member back on screen."""
    matrix = Mock(spec=Matrix)
    matrix._content_lock = RLock()
    matrix._content_queue = ContentQueue(mqtt_client, "/test/queue")
    matrix._attempt_combination.side_effect = partial(Matrix._attempt_combination, matrix)
    matrix._interrupt_for_queued_content.side_effect = partial(
        Matrix._interrupt_for_queued_content,
        matrix,
    )
    rain = Mock(spec=RainingGrid, id="rain", priority=10.0, active=True, stop_reason=None)
    clock = Mock(spec=Clock, id="clock", priority=15.0, active=True, stop_reason=None)
    combination = Mock(
        spec=Combination,
        id="combination",
        priority=10.0,
        active=True,
        stop_reason=None,
        content=(clock, rain),
    )
    combination.stop.side_effect = partial(ContentBase.stop, combination)
    matrix.current_content = combination
    alert = Mock(spec=GifViewer, id="alert", priority=1.0, stop_reason=None)
    matrix._content = {"alert": alert}
    parameters = cast("ContentParameters", {})
    ContentBase.stop(rain, StopType.CANCEL)

    def drain() -> Iterator[None]:
        yield
        Matrix._queue_content_message(
            matrix,
            {"id": "alert", "priority": 1, "parameters": parameters},
        )
        yield

    draining_child = drain()
    next(draining_child)
    next(draining_child)
    assert combination.stop_reason == StopType.PRIORITY
    Matrix._handle_content_stop(matrix, parameters, Mock())

    assert Matrix._get_next_content(matrix)[0] is alert
    assert Matrix._get_next_content(matrix)[0] is clock
    assert matrix._content_queue.empty()
    assert rain.stop_reason == StopType.CANCEL
    assert rain.priority == const.MAX_PRIORITY


def test_clock_request_during_cancelled_rain_teardown_does_not_recreate_rain(
    mqtt_client: MqttClient,
) -> None:
    """A new clock request must not include rain which is only alive to finish draining."""
    matrix = Mock(spec=Matrix)
    matrix._content_lock = RLock()
    matrix._content_queue = ContentQueue(mqtt_client, "/test/queue")
    matrix._attempt_combination.side_effect = partial(Matrix._attempt_combination, matrix)
    matrix._interrupt_for_queued_content.side_effect = partial(
        Matrix._interrupt_for_queued_content,
        matrix,
    )
    rain = Mock(spec=RainingGrid, id="rain", priority=10.0, active=True, stop_reason=None)
    rain.stop.side_effect = partial(ContentBase.stop, rain)
    clock = Mock(spec=Clock, id="clock", priority=15.0, stop_reason=None)
    matrix.current_content = rain
    matrix._content = {"clock": clock}
    parameters = cast("ContentParameters", {})
    ContentBase.stop(rain, StopType.CANCEL)

    def teardown() -> Iterator[None]:
        yield
        Matrix._queue_content_message(
            matrix,
            {"id": "clock", "priority": 15, "parameters": parameters},
        )
        yield

    rain.teardown.side_effect = teardown
    Matrix._handle_content_stop(matrix, parameters, Mock())

    assert Matrix._get_next_content(matrix)[0] is clock
    assert matrix._content_queue.empty()
    matrix._sort_content.assert_not_called()
    assert rain.priority == const.MAX_PRIORITY


@pytest.mark.parametrize("reason", [StopType.CANCEL, StopType.EXPIRED])
def test_stale_queued_combination_dissolves_before_resumption(
    mqtt_client: MqttClient,
    reason: StopType,
) -> None:
    """Finalized children are filtered even when their combination was already queued."""
    matrix = Mock(spec=Matrix)
    matrix._content_queue = ContentQueue(mqtt_client, "/test/queue")
    rain = Mock(spec=RainingGrid, id="rain", priority=10.0, stop_reason=None)
    clock = Mock(spec=Clock, id="clock", priority=15.0, stop_reason=None)
    combination = Mock(
        spec=Combination,
        id="combination",
        priority=10.0,
        content=(rain, clock),
    )
    matrix._content_queue.add(combination, cast("ContentParameters", {}))
    ContentBase.stop(rain, reason)

    selected, _ = Matrix._get_next_content(matrix)

    assert selected is clock
    assert matrix._content_queue.empty()


def test_all_cancelled_queued_combination_is_discarded(mqtt_client: MqttClient) -> None:
    """An obsolete queued combination can drain to an empty queue without rendering."""
    matrix = Mock(spec=Matrix)
    matrix._content_queue = ContentQueue(mqtt_client, "/test/queue")
    rain = Mock(
        spec=RainingGrid,
        id="rain",
        priority=const.MAX_PRIORITY,
        stop_reason=StopType.CANCEL,
    )
    combination = Mock(spec=Combination, id="combination", priority=10.0, content=(rain,))
    matrix._content_queue.add(combination, cast("ContentParameters", {}))

    with pytest.raises(Empty):
        Matrix._get_next_content(matrix)

    assert matrix._content_queue.empty()


def test_explicit_request_can_restart_cancelled_content(mqtt_client: MqttClient) -> None:
    """A fresh request replaces the cancelled lifecycle rather than being filtered out."""
    matrix = Mock(spec=Matrix)
    matrix._content_queue = ContentQueue(mqtt_client, "/test/queue")
    matrix.current_content = None
    alert = Mock(
        spec=GifViewer,
        id="alert",
        priority=const.MAX_PRIORITY,
        stop_reason=StopType.CANCEL,
    )
    matrix._content = {"alert": alert}
    parameters = cast("ContentParameters", {})

    Matrix._queue_content_message(
        matrix,
        {"id": "alert", "priority": 1, "parameters": parameters},
    )

    assert Matrix._get_next_content(matrix)[0] is alert
    assert alert.stop_reason is None
