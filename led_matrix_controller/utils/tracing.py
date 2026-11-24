"""Bounded OTLP export for sampled display frames."""

from __future__ import annotations

from contextlib import contextmanager, nullcontext
from typing import TYPE_CHECKING

from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import StatusCode

if TYPE_CHECKING:
    from collections.abc import Iterator
    from contextlib import AbstractContextManager

    from opentelemetry.trace import Span, Tracer

_DISABLED = nullcontext()


def display_tracer(endpoint: str | None) -> Tracer | None:
    """Create a background exporter when the display service is enrolled.

    Args:
        endpoint: Full OTLP/HTTP trace receiver URL, or None to disable export.

    Returns:
        The controller tracer when export is enabled.
    """
    if endpoint is None:
        return None

    provider = TracerProvider(
        resource=Resource.create({"service.name": "led-matrix-controller"}),
    )
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, timeout=3)),
    )
    return provider.get_tracer("matrix.display")


def frame_trace(
    tracer: Tracer | None,
    kind: str,
    content_type: str,
) -> AbstractContextManager[Span | None]:
    """Select the trace context for a render attempt.

    Args:
        tracer: Tracer for a sampled frame, or None for the fast path.
        kind: Dynamic, prepared or blank frame.
        content_type: Controller content class.

    Returns:
        The sampled span context or a reusable empty context.
    """
    return _record_frame(tracer, kind, content_type) if tracer is not None else _DISABLED


@contextmanager
def _record_frame(tracer: Tracer, kind: str, content_type: str) -> Iterator[Span]:
    """Record a frame and classify errors without recording exception payloads.

    Args:
        tracer: Display tracer.
        kind: Frame path.
        content_type: Controller content class.

    Yields:
        The span to annotate at each hardware boundary.
    """
    with tracer.start_as_current_span(
        "matrix.frame",
        attributes={"matrix.frame.kind": kind, "matrix.content.type": content_type},
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        try:
            yield span
        except Exception as exc:
            span.set_attribute("error.type", type(exc).__name__)
            span.set_status(StatusCode.ERROR)
            raise
