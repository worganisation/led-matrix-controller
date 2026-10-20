"""Regression tests for interruption and completion of display content."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import Mock

import numpy as np
import pytest
from content.base import ContentBase, StopType
from content.combination import Combination
from content.dynamic_content import DynamicContent
from content.gif.viewer import GifViewer
from content.image.viewer import ImageViewer

if TYPE_CHECKING:
    from collections.abc import Generator


def test_gif_interrupt_preserves_stop_reason() -> None:
    """A cancelled GIF must not finish its remaining animation or expire."""
    gif = Mock(spec=GifViewer, canvas_count=100)
    frames = GifViewer.__iter__(gif)  # noqa: PLC2801 — Exercise the concrete iterator with a mock instance.
    next(frames)
    gif.active = False
    gif.stop_reason = StopType.PRIORITY

    assert list(frames) == []
    gif.stop.assert_not_called()


def test_image_expires_after_display() -> None:
    """A completed image must not be mistaken for resumable content."""
    image = Mock(spec=ImageViewer, ticks_to_sleep=0)

    assert list(ImageViewer.__iter__(image)) == [None]  # noqa: PLC2801 — Exercise the concrete iterator with a mock instance.
    image.stop.assert_called_once_with(StopType.EXPIRED)
    assert image.is_sleeping is False


def test_dynamic_interruption_does_not_advance_nested_animation() -> None:
    """Stopping a sorter-style multi-frame refresh must suspend its work immediately."""
    content = Mock(spec=DynamicContent)
    advances = []

    def refresh() -> Generator[None, None, None]:
        for frame in range(100):
            advances.append(frame)
            yield

    content.refresh_content.side_effect = refresh
    frames = DynamicContent.__iter__(content)  # noqa: PLC2801 — Exercise the concrete iterator with a mock instance.
    next(frames)
    content.active = False

    assert list(frames) == []
    assert advances == [0]


@pytest.mark.parametrize("reason", [StopType.PRIORITY, StopType.COMBINED])
def test_combined_child_skips_teardown_on_handoff(reason: StopType) -> None:
    """A child being resumed must retain its state rather than clear itself."""
    content = Mock(spec=ContentBase, active=False, stop_reason=reason)
    content.setup.return_value = None

    assert list(ContentBase.chain_generators(content)) == []
    content.teardown.assert_not_called()


def test_combined_child_cancel_runs_teardown() -> None:
    """Actual cancellation still performs the child's cleanup."""
    content = Mock(spec=ContentBase, active=False, stop_reason=StopType.CANCEL)
    content.setup.return_value = None
    content.teardown.return_value = iter([None])

    assert list(ContentBase.chain_generators(content)) == [None]
    content.teardown.assert_called_once_with()


def test_combination_keeps_survivor_generators() -> None:
    """A finished child must not restart other children's setup or iteration."""
    children = [Mock(spec=DynamicContent, id=f"child-{i}") for i in range(3)]
    for child in children:
        child.active = True
        child.IS_OPAQUE = True
        child.x_pos = child.y_pos = 0
        child.width = child.height = 1
        child.get_content.return_value = np.zeros((1, 1, 4), dtype=np.int_)
        child.chain_generators.return_value = (None for _ in range(3))

    children[0].chain_generators.return_value = (None for _ in range(0))
    children[0].active = False
    combination = Mock(
        spec=Combination,
        active=True,
        content=tuple(children),
        multiple_opaque=True,
        none_opaque=False,
        pixels=np.zeros((1, 1, 4), dtype=np.int_),
    )
    combination.content_ids = tuple(child.id for child in children)
    combination.get_content_chains.return_value = {
        child.id: child.chain_generators() for child in children
    }

    def update(
        _setting: str,
        content: tuple[DynamicContent, ...],
        *,
        invoke_callback: bool,
    ) -> None:
        assert invoke_callback
        combination.content = content
        combination.content_ids = tuple(child.id for child in content)

    combination.update_setting.side_effect = update
    frames = Combination.refresh_content(combination)
    next(frames)
    next(frames)

    frames.close()

    assert combination.content == tuple(children[1:])
    for child in children[1:]:
        child.chain_generators.assert_called_once_with()
