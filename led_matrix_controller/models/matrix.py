"""Constants and class for managing the RGB LED Matrix."""

from __future__ import annotations

from collections.abc import Generator
from heapq import heapify
from itertools import count
from json import dumps
from math import isfinite
from os import getpid, kill
from queue import Empty, PriorityQueue
from signal import SIGTERM
from threading import Condition, RLock, Thread
from time import monotonic, time
from types import MappingProxyType
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    Final,
    TypedDict,
    cast,
)

import numpy as np
from content import Combination
from content.base import (
    ContentBase,
    GridView,
    PreDefinedContent,
    StopType,
)
from content.dynamic_content import DynamicContent
from content.setting import Setting, TransitionableParameterSetting
from PIL import Image
from utils import const, mtrx
from utils.helpers import to_kebab_case
from wg_utilities.decorators import process_exception
from wg_utilities.loggers import get_streaming_logger

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from numpy.typing import DTypeLike, NDArray
    from utils.mqtt import MqttClient

    from .led_matrix_options import LedMatrixOptions

LOGGER = get_streaming_logger(__name__)


ContentParameters = MappingProxyType[str, str]


class ContentPayload(TypedDict):
    """Object sent via MQTT to display content on the matrix."""

    id: str
    priority: float | None
    parameters: ContentParameters


class Dimensions(TypedDict):
    """Dimensions of the matrix."""

    height: int
    width: int


class ContentQueue:
    """Thread-safe queue with stable priorities and FIFO ordering for ties."""

    class MqttMeta(TypedDict):
        """Metadata for MQTT messages."""

        id: str
        parameters: ContentParameters

    def __init__(self, mqtt_client: MqttClient, topic_root: str) -> None:
        self._queue: PriorityQueue[
            tuple[
                float,
                int,
                ContentBase[GridView] | ContentBase[mtrx.Canvas],
                ContentParameters,
            ]
        ] = PriorityQueue()
        self._sequence = count()
        self.mqtt_client = mqtt_client
        self.state_topic = f"/{topic_root.strip('/')}/state"
        self.attrs_topic = f"/{topic_root.strip('/')}/attributes"
        self.mqtt_client.add_topic_callback(self.attrs_topic, self.validate_queue_content)

    def get(
        self,
        block: bool = True,  # ruff:ignore[boolean-type-hint-positional-argument, boolean-default-value-positional-argument]
        timeout: float | None = None,
        *,
        pop: bool = True,
    ) -> tuple[
        float,
        ContentBase[GridView] | ContentBase[mtrx.Canvas],
        ContentParameters,
    ]:
        """Select the next item using the priority captured when it was queued."""
        if pop:
            priority, _, content, parameters = self._queue.get(block, timeout)
            content.priority = priority
            self.send_mqtt_messages()
        else:
            with self._queue.mutex:
                if not self._queue.queue:
                    raise Empty

                priority, _, content, parameters = self._queue.queue[0]

        return priority, content, parameters

    def add(
        self,
        content: ContentBase[GridView] | ContentBase[mtrx.Canvas],
        parameters: ContentParameters,
    ) -> None:
        """Queue a content instance once, replacing an earlier request for it."""
        if content.priority == const.MAX_PRIORITY or not isfinite(content.priority):
            LOGGER.warning(
                "Content %s has invalid priority %s",
                content.id,
                content.priority,
            )
            return

        with self._queue.mutex:
            self._queue.queue[:] = [
                entry for entry in self._queue.queue if entry[2] is not content
            ]
            self._queue.queue.append(
                (round(content.priority, 3), next(self._sequence), content, parameters),
            )
            heapify(self._queue.queue)
            self._queue.not_empty.notify()

        self.send_mqtt_messages()

    def remove(
        self,
        content: ContentBase[GridView] | ContentBase[mtrx.Canvas],
        parameters: ContentParameters,
    ) -> None:
        """Remove a request and restore heap ordering atomically."""
        with self._queue.mutex:
            self._queue.queue[:] = [
                entry
                for entry in self._queue.queue
                if not (entry[2] is content and entry[3] == parameters)
            ]
            heapify(self._queue.queue)

        self.send_mqtt_messages()

    def empty(self) -> bool:
        """Whether there is any queued content."""
        return self._queue.empty()

    def qsize(self) -> int:
        """Number of queued requests."""
        return self._queue.qsize()

    def send_mqtt_messages(self) -> None:
        """Publish a consistent queue snapshot, including tied priorities."""
        attrs = self.mqtt_attributes
        self.mqtt_client.publish(
            topic=self.attrs_topic,
            payload=dumps(attrs),
            retain=True,
        )
        self.mqtt_client.publish(topic=self.state_topic, payload=len(attrs), retain=True)

    def validate_queue_content(self, payload: dict[str, MqttMeta]) -> None:
        """Ensure the retained MQTT messages match the queue."""
        if payload != self.mqtt_attributes:
            self.send_mqtt_messages()

    def __contains__(
        self,
        content_tuple: tuple[ContentBase[Any], ContentParameters],
    ) -> bool:
        """Check if the queue contains the content."""
        return any(c is content_tuple[0] and p == content_tuple[1] for _, c, p in self)

    def __iter__(
        self,
    ) -> Iterator[
        tuple[float, ContentBase[GridView] | ContentBase[mtrx.Canvas], ContentParameters]
    ]:
        """Iterate over an ordered snapshot rather than the live heap."""
        with self._queue.mutex:
            snapshot = sorted(self._queue.queue)

        return iter(
            (priority, content, parameters)
            for priority, _, content, parameters in snapshot
        )

    @property
    def mqtt_attributes(self) -> dict[str, MqttMeta]:
        """MQTT attributes with stable queued priorities and unique keys for ties."""
        attributes: dict[str, ContentQueue.MqttMeta] = {}
        for priority, content, parameters in self:
            key = f"{priority:.3f}"
            suffix = 2
            while key in attributes:
                key = f"{priority:.3f}:{suffix}"
                suffix += 1

            attributes[key] = {"id": content.id, "parameters": parameters}

        return attributes


class Matrix:
    """Class for displaying track information on an RGB LED Matrix."""

    COMBINATION_OVERRIDES: ClassVar[dict[tuple[str, ...], tuple[str, ...]]] = {
        ("clock", "raining-grid"): (
            "clock",
            "raining-grid",
        ),  # Rainfall in front of clock
        ("clock", "now-playing"): ("now-playing", "clock"),
    }
    """Overrides for content combination ordering.

    Key is combination, sorted alphabetically.
    Value is the combination's content in the desired order, from back to front.
    """

    OPTIONS: ClassVar[LedMatrixOptions] = {
        "cols": const.MATRIX_HEIGHT,
        "rows": const.MATRIX_WIDTH,
        "brightness": 100,
        "gpio_slowdown": 4,
        "hardware_mapping": "adafruit-hat-pwm",
        "show_refresh_rate": const.DEBUG_MODE,
        "limit_refresh_rate_hz": const.TICKS_PER_SECOND,
        "pwm_lsb_nanoseconds": 80,
        # "pwm_dither_bits": 1,  # ruff:ignore[commented-out-code]
    }

    PROGRESS_PUBLISH_INTERVAL: ClassVar[float] = 5.0

    canvas: mtrx.Canvas
    tick_condition: Condition

    id: Final = "matrix"

    def __init__(
        self,
        *,
        mqtt_client: MqttClient,
        content_works_with: dict[type[ContentBase[Any]], set[type[ContentBase[Any]]]],
        options: LedMatrixOptions = OPTIONS,
    ) -> None:
        self.mqtt_client = mqtt_client
        self.content_works_with = content_works_with

        self._brightness_setting = TransitionableParameterSetting(
            minimum=0,
            maximum=100,
            transition_rate=0.1,
            fp_precision=0,
            icon="mdi:brightness-percent",
            unit_of_measurement="%",
        ).setup(
            field_name="brightness",
            instance=self,
            type_=int,
        )
        self.mqtt_client.add_topic_callback(
            self._brightness_setting.mqtt_topic,
            self._brightness_setting.on_message,
        )

        self._brightness_setting.matrix = self
        self._brightness = options["brightness"]

        all_options = mtrx.RGBMatrixOptions()
        for name, value in options.items():
            setattr(all_options, name, value)

        self.matrix = mtrx.RGBMatrix(options=all_options)
        self.canvas = self.matrix.CreateFrameCanvas()

        self._content: dict[str, ContentBase[Any]] = {}

        self.queue_content_topic = self.mqtt_topic("queue-content")
        self.mqtt_client.add_topic_callback(
            self.queue_content_topic,
            self._on_content_message,
        )

        self.current_content_topic = self.mqtt_topic("current-content")

        self._content_queue = ContentQueue(
            mqtt_client=self.mqtt_client,
            topic_root=self.mqtt_topic("content-queue"),
        )

        self._content_lock = RLock()
        self._content_thread: Thread | None = None

        # Setting via property to trigger MQTT update
        self.current_content: ContentBase[GridView] | ContentBase[mtrx.Canvas] | None = (
            None
        )

        self._last_progress_publish = 0.0
        self.tick: int = 0
        self.tick_condition = Condition()

        self.array = self.zeros(dtype=np.uint8)

    def _attempt_combination(
        self,
        target_content: DynamicContent,
        combine_with: ContentBase[Any],
    ) -> Combination | None:
        """Combine compatible content, returning None when they must play separately."""
        if not isinstance(combine_with, DynamicContent) or target_content is combine_with:
            return None

        target_children = (
            target_content.content
            if isinstance(target_content, Combination)
            else (target_content,)
        )
        current_children = (
            combine_with.content
            if isinstance(combine_with, Combination)
            else (combine_with,)
        )
        children = tuple(
            {
                id(child): child for child in (*current_children, *target_children)
            }.values(),
        )
        if len(children) <= 1 or any(
            not self._content_works_with(left, right)
            for index, left in enumerate(children)
            for right in children[index + 1 :]
        ):
            return None

        combination = (
            combine_with
            if isinstance(combine_with, Combination)
            else target_content
            if isinstance(target_content, Combination)
            else cast("Combination", ContentBase.get("combination"))
        )
        combination.priority = min(child.priority for child in children)
        combined_content = self._sort_content(*children)
        if combine_with is not combination and combine_with.active:
            combine_with.stop(StopType.COMBINED, reset_priority=False)

        if combination.content != combined_content:
            combination.update_setting(
                "content",
                value=combined_content,
                invoke_callback=True,
            )

        return combination

    def _content_loop(self) -> None:
        """Run rendering and terminate the service if its worker fails."""
        try:
            self._run_content_loop()
        except Exception:
            LOGGER.exception("Rendering worker failed; terminating for service recovery")
            kill(getpid(), SIGTERM)

    def _run_content_loop(self) -> None:
        """Render queued content, serializing selection with incoming requests."""
        while True:
            with self._content_lock:
                if self._content_queue.empty():
                    self.clear_matrix()
                    # Release ownership before a producer can decide whether to start a worker.
                    self._content_thread = None
                    return

                content, parameters = self._get_next_content()
                content.stop_reason = None
                content.active = True
                self.current_content = content

            LOGGER.info(
                "Displaying content %s at priority %s",
                content.id,
                content.priority,
            )
            set_content = (
                self.set_image_swap_canvas
                if content.canvas_count is None
                else self.get_canvas_swap_canvas
            )

            if content.active and (setup_gen := content.setup()) is not None:
                for _ in setup_gen:
                    if not content.active:
                        break

                    set_content()

            self._render_content(content, set_content)
            self._handle_content_stop(parameters, set_content)

    def _render_content(
        self,
        content: ContentBase[Any],
        set_content: Callable[[], None],
    ) -> None:
        """Enter lazy iterators atomically with activation, then render without the lock."""
        with self._content_lock:
            if not content.active:
                return

            frames = iter(content)
            try:
                next(frames)
            except StopIteration:
                return

        try:
            if content.active:
                set_content()

            for _ in frames:
                if not content.active:
                    break

                set_content()
        finally:
            if isinstance(frames, Generator):
                frames.close()

    def _content_works_with(
        self,
        cls_a: type[ContentBase[Any]] | ContentBase[Any],
        cls_b: type[ContentBase[Any]] | ContentBase[Any],
    ) -> bool:
        """Check if the classes are compatible."""
        if not isinstance(cls_a, type):
            cls_a = cls_a.__class__

        if not isinstance(cls_b, type):
            cls_b = cls_b.__class__

        return cls_b in self.content_works_with.get(cls_a, set())

    def _get_next_content(
        self,
        *,
        dry_run: bool = False,
    ) -> tuple[ContentBase[Any], ContentParameters]:
        """Get the next content from the queue and check for available combinations."""
        (
            _,
            next_content,
            parameters,
        ) = self._content_queue.get(pop=not dry_run)

        if dry_run:
            return next_content, parameters

        to_remove = []

        # Check if the new content can be combined with anything else that is queued
        for _, queued_content, q_prms in self._content_queue:
            if (
                isinstance(queued_content, DynamicContent)
                and (
                    combined := self._attempt_combination(
                        queued_content,
                        combine_with=next_content,
                    )
                )
                is not None  # Incompatible content must remain queued for separate playback.
            ):
                # Combination has been created, so overwrite the current content
                next_content = combined

                to_remove.append((queued_content, q_prms))

        for queued_content, q_prms in to_remove:
            self._content_queue.remove(queued_content, q_prms)

        return next_content, parameters

    def _handle_content_stop(
        self,
        parameters: ContentParameters,
        set_content: Callable[[], None],
    ) -> None:
        """Handle the content stopping."""
        if self.current_content is None:
            return

        if self.current_content.stop_reason == StopType.TRANSFORM_REQUIRED and isinstance(
            self.current_content,
            Combination,
        ):
            # Unlikely to ever be more than one iteration, but just in case
            for c in self.current_content.content:
                if c.priority != const.MAX_PRIORITY and c.stop_reason not in {
                    StopType.CANCEL,
                    StopType.EXPIRED,
                }:
                    LOGGER.debug(
                        "Adding %r to queue with priority %f from stopping combination",
                        c.id,
                        c.priority,
                    )
                    self._content_queue.add(c, {})  # type: ignore[arg-type]
                else:
                    LOGGER.warning(
                        "Skipping stopped combination child %r with priority %f",
                        c.id,
                        c.priority,
                    )

        elif (
            self.current_content.stop_reason
            not in {
                StopType.PRIORITY,
                StopType.COMBINED,  # Preserve the content's state for reuse in the combination.
            }
            and (teardown_gen := self.current_content.teardown())
        ):
            LOGGER.info(
                "Running teardown sequence for %s",
                self.current_content.id,
            )

            for _ in teardown_gen:
                if self.current_content.stop_reason in {
                    StopType.PRIORITY,
                    StopType.COMBINED,
                }:
                    break

                set_content()

        self.current_content.active = False

        LOGGER.info("Content `%s` complete", self.current_content.id)

        with self._content_lock:
            if (
                self.current_content.priority != const.MAX_PRIORITY
                and self.current_content.stop_reason
                not in {StopType.CANCEL, StopType.EXPIRED, StopType.COMBINED}
                and not any(
                    isinstance(queued_content, Combination)
                    and self.current_content in queued_content.content
                    for _, queued_content, _ in self._content_queue
                )
            ):
                self._content_queue.add(self.current_content, parameters)

    @process_exception(logger=LOGGER, raise_after_processing=False)
    def _on_content_message(
        self,
        payload: ContentPayload,
    ) -> None:
        """Add/remove content to/from the queue."""
        with self._content_lock:
            self._queue_content_message(payload)

    def _queue_content_message(self, payload: ContentPayload) -> None:
        """Apply a content request while holding the scheduler lock."""
        target_content = self._content[payload["id"]]
        priority = payload["priority"]
        if priority is not None and not isfinite(priority):
            raise ValueError("Content priority must be finite")

        target_content.priority = const.MAX_PRIORITY if priority is None else priority
        parameters = payload.get("parameters", {})

        if target_content.priority == const.MAX_PRIORITY:  # i.e. null, i.e. de-queue
            self._remove_content(target_content)
            return

        target_content.priority = round(
            max(
                min(float(target_content.priority), const.MAX_PRIORITY),
                -const.MAX_PRIORITY,
            ),
            3,
        )

        # If they're both dynamic, they could be combined
        if isinstance(target_content, DynamicContent) and self.current_content:
            target_content = (
                self._attempt_combination(target_content, self.current_content)
                or target_content
            )

        if self.current_content is target_content:
            LOGGER.debug(
                "Updating %s priority to %s",
                target_content.id,
                target_content.priority,
            )
            self.current_content.priority = target_content.priority
            self._interrupt_for_queued_content()
            return

        if (
            isinstance(self.current_content, Combination)
            and target_content in self.current_content.content
        ):
            LOGGER.debug(
                "Content %r is already in combination %r, not adding to queue",
                target_content.id,
                ", ".join(c.id for c in self.current_content.content),
            )
            return

        # Add it to the queue, this will get picked up within the _content_loop
        self._content_queue.add(target_content, parameters)

        LOGGER.info(
            "Added content with ID `%s` to queue with priority %s",
            target_content.id,
            target_content.priority,
        )

        self._interrupt_for_queued_content()
        self._start_content_thread()

    def _interrupt_for_queued_content(self) -> None:
        """Yield to the queue when its first request outranks the current content."""
        if self.current_content is None or self.current_content.stop_reason in {
            StopType.PRIORITY,
            StopType.COMBINED,
        }:
            return

        try:
            priority, _, _ = self._content_queue.get(pop=False)
        except Empty:
            return

        if priority < self.current_content.priority:
            self.current_content.stop(StopType.PRIORITY, reset_priority=False)

    def _remove_content(self, target_content: ContentBase[Any]) -> None:
        """Handle a request to remove content from the queue."""
        for _, ctnt, prms in tuple(self._content_queue):
            if ctnt is target_content:
                self._content_queue.remove(ctnt, prms)
                LOGGER.info(
                    "Removed content with ID `%s` from queue",
                    target_content.id,
                )
            elif isinstance(ctnt, Combination) and any(
                child is target_content for child in ctnt.content
            ):
                self._content_queue.remove(ctnt, prms)
                for child in ctnt.content:
                    if child is not target_content:
                        self._content_queue.add(child, prms)

        if self.current_content is target_content:
            LOGGER.info(
                "Cancelling current content with ID `%s`",
                target_content.id,
            )
            self.current_content.stop(StopType.CANCEL)
        elif isinstance(self.current_content, Combination):
            for combined_content in self.current_content.content:
                if combined_content is target_content:
                    combined_content.stop(StopType.CANCEL)
                    LOGGER.info(
                        "Removed content with ID `%s` from combination",
                        target_content.id,
                    )
                    break

    def _sort_content(self, *content: ContentBase[Any]) -> tuple[ContentBase[Any], ...]:
        """Sort the content by priority, or override."""
        if override_ids := self.COMBINATION_OVERRIDES.get(
            tuple(sorted(c.id for c in content)),
        ):
            return ContentBase.get_many(override_ids)

        return tuple(
            sorted(
                content,
                key=lambda c: (not c.IS_OPAQUE, -c.priority),
            ),
        )

    def _start_content_thread(self) -> None:
        """Start a worker unless one already owns the queue."""
        with self._content_lock:
            if self._content_thread is not None:
                return

            self._content_thread = Thread(target=self._content_loop)
            self._content_thread.start()

    def clear_matrix(self) -> None:
        """Clear the matrix."""
        if self.current_content is not None:
            LOGGER.warning(
                "Clearing matrix with content %r still active at priority %f",
                self.current_content.id,
                self.current_content.priority,
            )
        self.current_content = None

        self.canvas.Clear()
        self.swap_canvas()

        LOGGER.info("Matrix cleared")

    def get_canvas_swap_canvas(self) -> None:
        """Get the canvas and swap it."""
        self.swap_canvas(self.current_content.get_content())  # type: ignore[union-attr]

    def new_canvas(self, image: Image.Image | None = None) -> mtrx.Canvas:
        """Return a new canvas, optionally with an image."""
        canvas = cast("mtrx.Canvas", self.matrix.CreateFrameCanvas())

        if image is not None:
            # Handle transparency by compositing onto black background
            if image.mode in {"RGBA", "LA"}:
                # Create a black background and composite the image onto it
                background = Image.new("RGB", image.size, (0, 0, 0))
                background.paste(image, mask=image.split()[-1])
                image = background
            elif image.mode == "P" and "transparency" in image.info:
                # Convert palette mode with transparency to RGBA first, then composite
                image = image.convert("RGBA")
                background = Image.new("RGB", image.size, (0, 0, 0))
                background.paste(image, mask=image.split()[-1])
                image = background
            else:
                image = image.convert("RGB")

            canvas.SetImage(image)

        return canvas

    def register_content(self, *content: ContentBase[Any]) -> None:
        """Add content to the matrix."""
        for c in content:
            c.validate_setup()

            self._content[c.id] = c

            setting: Setting[Any]
            for setting in getattr(c, "settings", {}).values():
                setting.matrix = self

            LOGGER.info("Added content with ID `%s`", c.id)

            if isinstance(c, PreDefinedContent):
                c.generate_canvases(self.new_canvas)

            if hasattr(c, "settings"):
                for setting in c.settings.values():
                    self.mqtt_client.add_topic_callback(
                        setting.mqtt_topic,
                        setting.on_message,
                    )

    def set_image_swap_canvas(self) -> None:
        """Set the image and swap the canvas."""
        content_array = self.current_content.get_content()  # type: ignore[union-attr]

        self.array.fill(0)

        x, y = self.current_content.position  # type: ignore[union-attr]

        self.array[
            y : y + self.current_content.height,  # type: ignore[union-attr]
            x : x + self.current_content.width,  # type: ignore[union-attr]
        ] = content_array

        image = Image.fromarray(self.array, "RGBA").convert("RGB")

        self.canvas.SetImage(image)

        self.swap_canvas(self.canvas)

    def swap_canvas(self, content: mtrx.Canvas | None = None, /) -> None:
        """Update the content of the canvas and increment the tick count."""
        self.canvas = self.matrix.SwapOnVSync(content or self.canvas)

        self.tick += 1

        if (
            now := monotonic()
        ) - self._last_progress_publish >= self.PROGRESS_PUBLISH_INTERVAL:
            self.mqtt_client.publish(
                topic=self.mqtt_topic("render-progress"),
                payload=dumps({"frame": self.tick, "rendered_at": time()}),
                retain=True,
            )
            self._last_progress_publish = now

        if self.tick_condition.acquire(timeout=const.TICK_LENGTH):
            try:
                self.tick_condition.notify_all()
            finally:
                self.tick_condition.release()

    def zeros(self, *, dtype: DTypeLike = np.int_) -> NDArray[Any]:
        """Return a grid of zeros."""
        return np.zeros((self.height, self.width, 4), dtype=dtype)

    @classmethod
    def mqtt_topic(cls, suffix: str) -> str:
        """Create an MQTT topic with the given suffix."""
        return "/" + "/".join(
            to_kebab_case(const.HOSTNAME, cls.__name__, *suffix.split("/")),
        )

    @property
    def active(self) -> bool:
        """Whether content is currently playing."""
        return self.current_content is not None and self.current_content.active

    @property
    def dimensions(self) -> Dimensions:
        """Dimensions of the matrix."""
        return {
            "height": self.height,
            "width": self.width,
        }

    @property
    def height(self) -> int:
        """Height of the matrix."""
        return int(self.matrix.height)

    @property
    def width(self) -> int:
        """Width of the matrix."""
        return int(self.matrix.width)

    @property
    def brightness(self) -> int:
        """Brightness of the matrix."""
        return self._brightness

    @brightness.setter
    def brightness(self, value: int) -> None:
        """Set the brightness of the matrix."""
        self._brightness = value
        self.matrix.brightness = value

        LOGGER.debug("Set brightness to %s (%i)", value, self.tick)

        # If there is no content playing, actively swap the canvas to update the brightness
        # Otherwise the brightness will be updated on each tick anyway
        if self.current_content is None or self.current_content.is_sleeping:
            self.swap_canvas()

    @property
    def current_content(self) -> ContentBase[Any] | None:
        """Currently displaying content."""
        return self._current_content

    @current_content.setter
    def current_content(self, value: ContentBase[Any] | None) -> None:
        self._current_content = value

        self.mqtt_client.publish(
            topic=self.current_content_topic,
            payload=value.id if value is not None else None,
            retain=True,
        )
        LOGGER.info(
            "Current Content: %s",
            value.id if value is not None else None,
        )

        self.publish_attributes()

    def publish_attributes(self) -> None:
        """Publish the attributes of the current content."""
        self.mqtt_client.publish(
            topic=f"{self.current_content_topic}/attributes",
            payload=self.current_content.mqtt_attributes
            if self.current_content is not None
            else "{}",
        )

    def __del__(self) -> None:
        """Clear the matrix when the object is deleted."""
        self.clear_matrix()

    def setting_update_callback(self, *_: Any, **__: Any) -> None:
        """Generate the frame rulesets for the matrix."""
        raise NotImplementedError
