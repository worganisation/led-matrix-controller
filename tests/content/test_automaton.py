"""Simulation scheduling, shutdown and rain clearing regressions."""

from __future__ import annotations

from queue import Queue
from threading import Event
from typing import TYPE_CHECKING

import numpy as np
import pytest
from content import base
from content.base import StopType
from content.raining_grid import RainingGrid, State

if TYPE_CHECKING:
    from collections.abc import Generator


@pytest.fixture
def grid(monkeypatch: pytest.MonkeyPatch) -> Generator[RainingGrid, None, None]:
    """Always stop the actual simulation worker."""
    monkeypatch.setattr(base, "_CONTENT_STORE", {})
    simulation = RainingGrid(height=16, width=16, rain_chance=0.025)
    yield simulation
    simulation._stop_rules_thread()


def test_large_coprime_frequencies_have_bounded_schedule(grid: RainingGrid) -> None:
    """Legal coprime settings must not materialize their multi-billion-frame LCM."""
    grid.settings["rain_speed"].value = 997
    grid.settings["splash_speed"].value = 991
    grid.setting_update_callback()

    assert len(grid._rule_schedule) == len(grid.rules)
    assert {997, 991} <= {frequency for frequency, _ in grid._rule_schedule}
    frames = iter(grid)
    next(frames)
    frames.close()


def test_scheduler_preserves_rule_cadence(grid: RainingGrid) -> None:
    """A rule runs on frame zero and multiples of its interval, including after resume."""
    mask = np.zeros(grid.shape, dtype=np.bool_)
    mask[0, 0] = True
    grid._rule_schedule = (
        (3, ((slice(None), slice(None)), lambda _: mask, 1, lambda _: True, 1)),
    )
    frames = iter(grid)
    next(frames)
    assert grid.pixels[0, 0] == 1
    frames.close()

    grid.pixels[:] = 0
    frames = iter(grid)
    next(frames)
    assert grid.pixels[0, 0] == 0
    next(frames)
    assert grid.pixels[0, 0] == 0
    next(frames)
    assert grid.pixels[0, 0] == 1
    frames.close()


def test_full_queue_worker_stops(grid: RainingGrid) -> None:
    """A producer with a full queue can stop without a consumer draining it."""
    generated = Event()
    produced = 0

    def generate(_: object) -> np.typing.NDArray[np.bool_]:
        nonlocal produced
        produced += 1
        if produced == 2:
            generated.set()

        return grid.fresh_mask()

    grid.mask_queue = Queue(maxsize=1)
    grid._rule_schedule = (
        (
            1,
            (
                (slice(None), slice(None)),
                generate,
                0,
                lambda _: True,
                1,
            ),
        ),
    )
    grid._start_rules_thread()
    assert generated.wait(timeout=1)
    grid._stop_rules_thread()
    assert not grid._rules_thread.is_alive()
    assert grid.mask_queue.empty()


def test_worker_exception_reaches_renderer(grid: RainingGrid) -> None:
    """A broken rule raises at the consumer instead of blocking on an empty queue."""

    def fail(_: object) -> np.typing.NDArray[np.bool_]:
        raise ValueError("broken rule")

    grid._rule_schedule = ((1, ((slice(None), slice(None)), fail, 0, lambda _: True, 1)),)
    frames = iter(grid)
    with pytest.raises(RuntimeError, match="simulation worker") as error:
        next(frames)

    assert isinstance(error.value.__cause__, ValueError)
    assert not grid._rules_thread.is_alive()


def test_interrupted_teardown_preserves_new_settings(grid: RainingGrid) -> None:
    """Clearing uses a transient rain override and preserves a concurrent setting update."""
    grid.pixels[-1, 5] = State.MATURE_PLANT.state
    teardown = grid.teardown()
    next(teardown)
    assert grid.effective_rain_chance == 0

    grid.settings["rain_chance"].value = 0.05
    grid.stop(StopType.PRIORITY)
    with pytest.raises(StopIteration):
        next(teardown)

    assert grid.rain_chance == pytest.approx(0.05)
    assert grid.effective_rain_chance == pytest.approx(0.05)
    assert not grid._rules_thread.is_alive()


def test_closed_teardown_restores_rain(grid: RainingGrid) -> None:
    """Closing a clearing generator also releases its worker and temporary override."""
    original = grid.rain_chance
    teardown = grid.teardown()
    next(teardown)
    teardown.close()
    assert grid.effective_rain_chance == original
    assert not grid._rules_thread.is_alive()


def test_plant_spacing_uses_columns(grid: RainingGrid) -> None:
    """An existing plant excludes nearby columns away from the left edge."""
    grid.plant_growth_chance = 1
    grid.pixels[-1, 8] = State.MATURE_PLANT.state
    grid.pixels[-2, 10] = State.SPLASHDROP.state
    rule = next(rule for rule in grid.rules if rule.rule_func.__name__ == "start_plant")
    assert not rule.mask_generator(grid.pixels).any()

    grid.pixels[-2, 10] = State.NULL.state
    grid.pixels[-2, 2] = State.SPLASHDROP.state
    mask = rule.mask_generator(grid.pixels)
    assert mask.sum() == 1
    assert mask[0, 1]
