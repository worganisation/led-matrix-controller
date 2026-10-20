"""Benchmark the pre-commit hooks."""

from __future__ import annotations

from itertools import islice, product
from typing import TYPE_CHECKING

import numpy as np
import pytest
from content import RainingGrid
from utils import const

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

    from content.automaton import MaskGen
    from pytest_codspeed import BenchmarkFixture

SIZES = [16]
LIMITS = [50]


@pytest.fixture
def grid(
    size: int, test_id: str, monkeypatch: pytest.MonkeyPatch,
) -> Generator[RainingGrid, None, None]:
    """Stop each benchmark's simulation worker when the test finishes."""
    monkeypatch.setattr(const, "RNG", np.random.default_rng(0))
    simulation = RainingGrid(
        height=size,
        width=size,
        rain_chance=0.025,
        rain_speed=1,
        splash_speed=1,
        id_override=test_id,
    )

    yield simulation

    if hasattr(simulation, "_rules_thread"):
        simulation._stop_rules_thread()


@pytest.mark.parametrize(
    ("size", "limit", "test_id"),
    [
        pytest.param(
            size,
            limit,
            test_id := f"{limit} frame{'s' if limit > 1 else ''} @ {size}x{size}",
            id=test_id,
        )
        for size, limit in product(
            SIZES,
            LIMITS,
        )
    ],
)
def test_raining_grid_simulation(
    benchmark: BenchmarkFixture,
    grid: RainingGrid,
    limit: int,
) -> None:
    """Benchmark the CA."""

    @benchmark
    def bench() -> None:
        for _ in grid.islice(limit=limit):
            pass


@pytest.mark.parametrize(
    ("size", "limit", "rule", "test_id"),
    [
        pytest.param(
            size,
            limit,
            rule,
            test_id
            := f"{rule.__name__} for {limit} frame{'s' if limit > 1 else ''} @ {size}x{size}",
            id=test_id,
        )
        for size, limit, rule in product(
            SIZES,
            LIMITS,
            RainingGrid._RULE_FUNCTIONS,
        )
    ],
)
def test_rules(
    benchmark: BenchmarkFixture,
    grid: RainingGrid,
    size: int,
    limit: int,
    rule: Callable[..., MaskGen],
) -> None:
    """Test/benchmark each individual rule."""
    # Discard the first `size` frames so all rules are effective (e.g. splashing)
    for _ in islice(grid, size + 10):
        pass

    expected_frame_index = size + 9
    assert grid.frame_index == expected_frame_index
    frames = [grid.pixels.copy() for _ in islice(grid, limit)]

    grid._stop_rules_thread()
    mask_gen = rule(grid)

    @benchmark
    def bench() -> None:
        for pixels in frames:
            mask_gen(pixels)
