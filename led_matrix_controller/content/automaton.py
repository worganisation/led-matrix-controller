"""Cellular Automata module."""

from __future__ import annotations

from abc import ABC
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, field
from enum import IntEnum
from functools import lru_cache, wraps
from itertools import islice
from os import getenv
from queue import Empty, Full, Queue
from threading import Event, Thread
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    Final,
    Self,
)

import numpy as np
from models.rule import Rule
from numpy.typing import NDArray
from utils import const
from wg_utilities.loggers import get_streaming_logger

from .base import GridView, StateBase
from .dynamic_content import DynamicContent
from .setting import FrequencySetting

if TYPE_CHECKING:
    from collections.abc import Generator

LOGGER = get_streaming_logger(__name__)


EVERYWHERE = (slice(None), slice(None))


class Direction(IntEnum):
    """Enum representing the direction of a cell."""

    LEFT = -1
    RIGHT = 1
    UP = -1
    DOWN = 1


TargetSliceDecVal = slice | int | tuple[int | slice, int | slice]
TargetSlice = tuple[slice, slice]
Mask = NDArray[np.bool_]
MaskGen = Callable[[GridView], Mask]
RuleFunc = Callable[["Automaton", TargetSlice], MaskGen]
RuleTuple = tuple[
    TargetSlice,
    MaskGen,
    int | tuple[int, ...],
    Callable[["Automaton"], bool],
    float,
]
RuleSchedule = tuple[tuple[int, RuleTuple], ...]

QUEUE_SIZE: Final[int] = int(getenv("AUTOMATON_QUEUE_SIZE", "100"))


@dataclass(kw_only=True, slots=True)
class Automaton(DynamicContent, ABC):
    """Base class for a grid of cells."""

    STATE: ClassVar[type[StateBase]]
    _RULES_SOURCE: ClassVar[list[Rule]] = []
    if const.DEBUG_MODE:
        _RULE_FUNCTIONS: ClassVar[list[Callable[..., MaskGen]]] = []

    TRACK_STATES_DURATION: ClassVar[tuple[int, ...]] = ()

    frame_index: int = field(init=False, default=-1)
    _rule_schedule: RuleSchedule = field(init=False, repr=False)
    rules: list[Rule] = field(init=False, repr=False)

    _rules_thread: Thread = field(init=False, repr=False)
    mask_queue: Queue[GridView] = field(init=False, repr=False)
    _rules_stop: Event = field(init=False, default_factory=Event, repr=False)
    _rules_error: Exception | None = field(init=False, default=None, repr=False)

    durations: GridView = field(init=False, repr=False)

    class OutOfBoundsError(ValueError):
        """Error for when a slice goes out of bounds."""

        def __init__(self, current: int | None, delta: int, limit: int) -> None:
            """Initialize the OutOfBoundsError."""
            self.current = current
            self.delta = delta
            self.limit = limit

            super().__init__(f"Out of bounds: {current} + {delta} > {limit}")

    def __post_init__(self) -> None:
        """Set the calculated attributes of the Grid."""
        DynamicContent.__post_init__(self)

        self.colormap = self.STATE.colormap()
        self.rules = deepcopy(self._RULES_SOURCE)

        # Create the automaton; 0 is the default state
        self.pixels = self.zeros()
        self.durations = self.zeros()

        # Create mask generators after all setup is done
        for rule in self.rules:
            if isinstance(rule.frequency, str) and isinstance(
                freq_setting := self.settings.get(rule.frequency),
                FrequencySetting,
            ):
                rule._frequency_setting = freq_setting  # ruff:ignore[private-member-access]

            rule.target_view = self.pixels[rule.target_slice]
            rule.refresh_mask_generator(self)

        self.setting_update_callback()

        self.mask_queue = Queue(maxsize=QUEUE_SIZE)

    def setting_update_callback(self, update_setting: str | None = None) -> None:
        """Publish a bounded snapshot of rule frequencies and generators."""
        if update_setting:
            for rule in self.rules:
                if update_setting in rule.consumed_parameters:
                    rule.refresh_mask_generator(self)

        Rule.clear_cached_rule_tuples()

        self._rule_schedule = tuple(
            (rule.current_frequency, rule.rule_tuple(self)) for rule in self.rules
        )

    @classmethod
    def rule(
        cls,
        to_state: StateBase | tuple[StateBase, ...],
        *,
        target_slice: TargetSliceDecVal = EVERYWHERE,
        frequency: int | str = 1,
        predicate: Callable[[Self], bool] = lambda _: True,
        random_multiplier: float | str = 1,
    ) -> Callable[[Callable[[Any, TargetSlice], MaskGen]], Callable[[Self], MaskGen]]:
        """Decorator to add a rule to the automaton.

        Args:
            to_state (StateBase): The state to change to.
            target_slice (TargetSliceDecVal | None, optional): The slice to target. Defaults to entire automaton.
            frequency (int, optional): The frequency of the rule (in frames). Defaults to 1 (i.e. every frame). If
                a string is provided, it references the name of a `FrequencySetting`.
            predicate (Callable[[], bool], optional): Optional predicate to determine if the rule should be
                applied.
            random_multiplier (float, optional): Optional random multiplier for the rule. Defaults to 1.
        """
        match target_slice:
            case int(n):
                actual_slice = (slice(n, n + 1), slice(None))
            case slice(start=x_start, stop=x_stop, step=x_step):
                actual_slice = (slice(x_start, x_stop, x_step), slice(None))
            case (int(n), slice(start=y_start, stop=y_stop, step=y_step)):
                actual_slice = (slice(n, n + 1), slice(y_start, y_stop, y_step))
            case (slice(start=x_start, stop=x_stop, step=x_step), int(y)):
                actual_slice = (slice(x_start, x_stop, x_step), slice(y, y + 1))
            case (
                slice(start=x_start, stop=x_stop, step=x_step),
                slice(start=y_start, stop=y_stop, step=y_step),
            ):
                actual_slice = (
                    slice(x_start, x_stop, x_step),
                    slice(y_start, y_stop, y_step),
                )
            case _:
                raise ValueError(f"Invalid target_slice: {target_slice}")

        del target_slice

        def decorator(
            rule_func: Callable[[Automaton, TargetSlice], MaskGen],
        ) -> Callable[[Automaton], MaskGen]:
            cls._RULES_SOURCE.append(
                Rule(
                    target_slice=actual_slice,
                    rule_func=rule_func,
                    to_state=to_state,
                    frequency=frequency,
                    predicate=predicate,  # type: ignore[arg-type]
                    random_multiplier=random_multiplier,
                ),
            )

            if const.DEBUG_MODE:
                # This is just to enable testing/debugging/validation/etc.
                @wraps(rule_func)
                def wrapper(automaton: Automaton) -> MaskGen:
                    return rule_func(automaton, actual_slice)

                cls._RULE_FUNCTIONS.append(wrapper)

                return wrapper

            return None  # The function is never explicitly called directly, only ever via Rule.rule_func

        return decorator

    def islice(self, limit: int) -> Generator[None, None, None]:
        """Run the simulation for a given number of frames."""
        yield from islice(self, limit)

    def fresh_mask(self) -> Mask:
        """Return a fresh mask."""
        return self.zeros(dtype=np.bool_)

    def refresh_content(self) -> Generator[None, None, None]:
        """Generate the frames of the automaton."""
        while self.active:
            if self._rules_error is not None:
                raise RuntimeError(
                    "Automaton simulation worker failed",
                ) from self._rules_error

            try:
                frame = self.mask_queue.get(timeout=0.1)
            except Empty:
                if not self.active:
                    return

                if not self._rules_thread.is_alive():
                    raise RuntimeError(
                        "Automaton simulation worker stopped unexpectedly",
                    ) from self._rules_error

                continue

            self.pixels[:, :] = frame
            self.frame_index += 1
            yield
            return

    def _rules_worker(self) -> None:
        """Produce frames until stopped, retaining failures for the rendering thread."""
        try:
            self._produce_frames()
        except Exception as error:  # ruff: ignore[blind-except] — Transfer worker failures to the rendering thread.
            self._rules_error = error

    def _produce_frames(self) -> None:
        pixels = self.pixels.copy()
        prev_pixels = pixels.copy()
        frame = self.frame_index + 1

        while self.active and not self._rules_stop.is_set():
            masks = tuple(
                (target_slice, mask_gen(pixels), state, rand_mult)
                for frequency, (
                    target_slice,
                    mask_gen,
                    state,
                    predicate,
                    rand_mult,
                ) in self._rule_schedule
                if frequency and frame % frequency == 0 and predicate(self)
            )

            for target_slice, mask, new_state, rand_mult in masks:
                if rand_mult < 1:
                    mask &= const.RNG.random(mask.shape) < rand_mult  # ruff:ignore[redefined-loop-name]

                if isinstance(new_state, int):
                    pixels[target_slice][mask] = new_state
                else:
                    pixels[target_slice][mask] = const.RNG.choice(
                        new_state,
                        size=mask.sum(),
                    )

            if self.TRACK_STATES_DURATION:
                tracked_states_mask = np.isin(pixels, self.TRACK_STATES_DURATION)
                same_state_mask = (pixels == prev_pixels) & tracked_states_mask
                new_tracked_state_mask = (pixels != prev_pixels) & tracked_states_mask

                self.durations[same_state_mask] += 1
                self.durations[new_tracked_state_mask] = 1
                self.durations[~tracked_states_mask] = 0

            prev_pixels = pixels.copy()
            while self.active and not self._rules_stop.is_set():
                try:
                    self.mask_queue.put(prev_pixels, timeout=0.1)
                except Full:
                    continue

                break

            frame += 1

    def _start_rules_thread(self) -> None:
        """Start a simulation worker, joining any previous run first."""
        self._stop_rules_thread()
        self.active = True
        self._rules_stop.clear()
        self._rules_error = None
        self._rules_thread = Thread(target=self._rules_worker)
        self._rules_thread.start()

    def _stop_rules_thread(self) -> None:
        """Stop the worker without waiting for a consumer to drain its queue."""
        self.active = False
        self._rules_stop.set()

        if hasattr(self, "_rules_thread"):
            self._rules_thread.join(timeout=1)
            if self._rules_thread.is_alive():
                raise RuntimeError("Automaton simulation worker did not stop")

        while True:
            try:
                self.mask_queue.get_nowait()
            except Empty:
                break

    @property
    def str_repr(self) -> str:
        """String representation of the automaton."""
        return "\n".join(" ".join(state.char for state in row) for row in self.pixels)

    def translate_slice(
        self,
        slice_: TargetSlice,
        /,
        *,
        vrt: int = 0,
        hrz: int = 0,
    ) -> TargetSlice:
        """Translate a slice in the vertical (down) and horizontal (right) directions.

        Args:
            slice_ (TargetSlice): The slice to translate.
            vrt (int, optional): The vertical translation: positive is down, negative is up. Defaults to 0.
            hrz (int, optional): The horizontal translation: positive is right, negative is left. Defaults to 0.
        """
        rows, cols = slice_
        return _translate_slice(
            rows_start=rows.start,
            rows_stop=rows.stop,
            rows_step=rows.step,
            cols_start=cols.start,
            cols_stop=cols.stop,
            cols_step=cols.step,
            vrt=vrt,
            hrz=hrz,
            height=self.height,
            width=self.width,
        )

    @property
    def shape(self) -> tuple[int, int]:
        """Shape of the automaton."""
        return self.pixels.shape  # type: ignore[return-value]

    @property
    def current_content(self) -> Self:
        """This automaton.

        Bit of a workaround to get Settings to play nice between Matrix and Automaton instances.
        """
        return self

    def __iter__(self) -> Generator[None, None, None]:
        """Iterate over the frames."""
        self.active = True

        self._start_rules_thread()

        try:
            while self.active:
                yield from self.refresh_content()
        finally:
            self._stop_rules_thread()

    def __hash__(self) -> int:
        """Return the hash of the automaton."""
        return hash(self.id)


@lru_cache
def _translate_slice(
    *,
    rows_start: int | None,
    rows_stop: int | None,
    rows_step: int,
    cols_start: int | None,
    cols_stop: int | None,
    cols_step: int,
    vrt: int = 0,
    hrz: int = 0,
    height: int,
    width: int,
) -> TargetSlice:
    return (
        slice(
            _translate_slice_start(
                current=rows_start,
                delta=vrt,
                size=height,
            ),
            _translate_slice_stop(
                current=rows_stop,
                delta=vrt,
                size=height,
            ),
            rows_step,
        ),
        slice(
            _translate_slice_start(
                current=cols_start,
                delta=hrz,
                size=width,
            ),
            _translate_slice_stop(
                current=cols_stop,
                delta=hrz,
                size=width,
            ),
            cols_step,
        ),
    )


def _translate_slice_start(*, current: int | None, delta: int, size: int) -> int | None:
    """Translate the start of a slice by a given delta.

    Takes into account the limit of the automaton: returns None if the slice goes out of bounds in a negative
    direction; raises an error if the slice goes out of bounds in a positive direction (because this means
    the entire slice has gone off the automaton).

    Args:
        delta (int): The translation delta.
        current (int | None): The current start of the slice.
        size (int): The limit of the automaton (either its height or width, depending on the slice direction)

    Returns:
        int | None: The new start of the slice.
    """
    if delta > 0:
        # Right/Down - can go OOB (trailing edge == off-grid in this direction)
        new_value = (current or 0) + delta

        upper_bound = (size - 1) if current is None or current >= 0 else -1
        if new_value > upper_bound:  # Gone off grid - not good!
            raise Automaton.OutOfBoundsError(current, delta, size)
    elif delta < 0:  # Left/Up - can't go OOB
        if current is None:  # Immediately going off grid, but that's okay
            new_value = None
        else:
            lower_bound = 0 if current >= 0 else -size

            if (new_value := current + delta) < lower_bound:
                new_value = None
    elif delta == 0:  # No change
        new_value = current

    return new_value


def _translate_slice_stop(*, current: int | None, delta: int, size: int) -> int | None:
    """Translate the stop of a slice by a given delta.

    Takes into account the limit of the grid: returns None if the slice goes out of bounds in a positive
    direction; raises an error if the slice goes out of bounds in a negative direction (because this means
    the entire slice has gone off the grid).

    Args:
        delta (int): The translation delta.
        current (int | None): The current stop of the slice.
        size (int): The limit of the grid (either its height or width, depending on the slice direction)

    Returns:
        int | None: The new stop of the slice.
    """
    if delta > 0:
        # Right/Down - can't go OOB (leading edge beacomes open end in this direction)
        if current is None:
            new_value = None
        else:
            upper_bound = (size - 1) if current >= 0 else -1

            if (new_value := current + delta) > upper_bound:  # i.e. gone off grid
                new_value = None
    elif delta < 0:
        # Left/Up - can go OOB (trailing edge == off-grid in this direction)
        new_value = (current or 0) + delta  # Negative number!

        lower_bound = 0 if current is not None and current >= 0 else -size
        if new_value < lower_bound:
            raise Automaton.OutOfBoundsError(current, delta, size)
    elif delta == 0:  # No change
        new_value = current

    return new_value
