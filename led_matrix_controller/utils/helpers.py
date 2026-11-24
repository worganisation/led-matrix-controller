"""Helper functions."""

from __future__ import annotations

import fcntl
import hashlib
import mmap
import os
import re
import struct
import tempfile
import time
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, overload

import numpy as np

from .const import AUDIO_VISUALISER_SHM_NAME

if TYPE_CHECKING:
    from numpy.typing import NDArray

MAX_AUDIO_CHUNK_SIZE = 20000
_AUDIO_HEADER = struct.Struct("QQd")
_AUDIO_BUFFER_SIZE = _AUDIO_HEADER.size + (MAX_AUDIO_CHUNK_SIZE // 2 + 1) * 8
_AUDIO_FRAME_MAX_AGE = 1.0
_LINUX_SHARED_MEMORY = Path("/dev/shm")  # ruff:ignore[hardcoded-temp-file] — Both services need the same memory-backed directory.
_AUDIO_FRAME_DIRECTORY = (
    _LINUX_SHARED_MEMORY if _LINUX_SHARED_MEMORY.is_dir() else Path(tempfile.gettempdir())
)


class Patterns(Enum):
    """Regex patterns."""

    NOT_LETTERS = re.compile(r"[^a-z]", flags=re.IGNORECASE)
    CAMELCASE = re.compile(r"(?<!^)(?=[A-Z])")
    MULTIPLE_HYPHENS = re.compile(r"-+")

    def sub(self, repl: str, string: str) -> str:
        """Substitute pattern with replacement."""
        return self.value.sub(repl, string)


@overload
def to_kebab_case(string: str) -> str: ...


@overload
def to_kebab_case(*string: str) -> tuple[str, ...]: ...


def to_kebab_case(*string: str) -> str | tuple[str, ...]:  # type: ignore[misc]
    """Convert string to kebab case."""
    if len(string) == 1:
        return _remove_multiple_hyphens(
            Patterns.NOT_LETTERS.sub("-", string[0]).casefold(),
        )

    return tuple(
        _remove_multiple_hyphens(
            *(Patterns.NOT_LETTERS.sub("-", s).casefold() for s in string),
        ),
    )


@overload
def camel_to_kebab_case(string: str) -> str: ...


@overload
def camel_to_kebab_case(*string: str) -> tuple[str, ...]: ...


def camel_to_kebab_case(*string: str) -> str | tuple[str, ...]:  # type: ignore[misc]
    """Convert camel case string to kebab case."""
    if len(string) == 1:
        return _remove_multiple_hyphens(Patterns.CAMELCASE.sub("-", string[0]).casefold())

    return tuple(
        _remove_multiple_hyphens(
            *(Patterns.CAMELCASE.sub("-", s).casefold() for s in string),
        ),
    )


@overload
def _remove_multiple_hyphens(string: str) -> str: ...


@overload
def _remove_multiple_hyphens(*string: str) -> tuple[str, ...]: ...


def _remove_multiple_hyphens(*string: str) -> str | tuple[str, ...]:  # type: ignore[misc]
    """Remove multiple hyphens."""
    if len(string) == 1:
        return Patterns.MULTIPLE_HYPHENS.sub("-", string[0]).strip("-")

    return tuple(Patterns.MULTIPLE_HYPHENS.sub("-", s).strip("-") for s in string)


@lru_cache(maxsize=128)
def hex_to_rgba(hex_code: str) -> tuple[int, int, int, int]:
    """Convert hex code to rgba tuple."""
    hex_code = hex_code.lstrip("#")

    if len(hex_code) == 6:  # ruff:ignore[magic-value-comparison]
        r, g, b = int(hex_code[0:2], 16), int(hex_code[2:4], 16), int(hex_code[4:6], 16)
        a = 255
    else:
        r, g, b, a = (int(hex_code[i : i + 2], 16) for i in (0, 2, 4, 6))

    return r, g, b, a


class AudioFrameBuffer:
    """Share a fixed-capacity FFT frame between independently restarted services.

    A file-backed mapping avoids the shared-memory resource tracker's process-exit
    unlinking. The file lock protects both metadata and samples as one frame.
    """

    def __init__(self) -> None:
        name = hashlib.sha256(AUDIO_VISUALISER_SHM_NAME.encode()).hexdigest()[:16]
        path = _AUDIO_FRAME_DIRECTORY / f"matrix-audio-{name}.frames"
        self._fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        fcntl.flock(self._fd, fcntl.LOCK_EX)
        try:
            if os.fstat(self._fd).st_size != _AUDIO_BUFFER_SIZE:
                os.ftruncate(self._fd, _AUDIO_BUFFER_SIZE)
            self._mapping = mmap.mmap(self._fd, _AUDIO_BUFFER_SIZE)
        finally:
            fcntl.flock(self._fd, fcntl.LOCK_UN)

    def write(
        self,
        magnitudes: NDArray[np.float64],
        chunk_size: int,
        sample_rate: int,
    ) -> None:
        """Publish one complete frame with the configuration that produced it."""
        if not 1 <= chunk_size <= MAX_AUDIO_CHUNK_SIZE:
            raise ValueError("Audio chunk size exceeds shared frame capacity")
        if magnitudes.shape != (chunk_size // 2 + 1,):
            raise ValueError("Audio frame length does not match its chunk size")

        fcntl.flock(self._fd, fcntl.LOCK_EX)
        try:
            # An interrupted writer must leave an invalid frame, never partial samples.
            _AUDIO_HEADER.pack_into(self._mapping, 0, 0, 0, 0)
            destination: NDArray[np.float64] = np.ndarray(
                magnitudes.shape,
                dtype=np.float64,
                buffer=self._mapping,
                offset=_AUDIO_HEADER.size,
            )
            np.copyto(destination, magnitudes)
            _AUDIO_HEADER.pack_into(
                self._mapping,
                0,
                chunk_size,
                sample_rate,
                time.monotonic(),
            )
        finally:
            fcntl.flock(self._fd, fcntl.LOCK_UN)

    def read(
        self,
        destination: NDArray[np.float64],
        chunk_size: int,
        sample_rate: int,
    ) -> bool:
        """Copy a matching fresh frame without blocking the rendering thread."""
        try:
            fcntl.flock(self._fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            return False

        try:
            frame_chunk, frame_rate, timestamp = _AUDIO_HEADER.unpack_from(self._mapping)
            if (
                (frame_chunk, frame_rate) != (chunk_size, sample_rate)
                or not 0 <= time.monotonic() - timestamp <= _AUDIO_FRAME_MAX_AGE
                or destination.shape != (chunk_size // 2 + 1,)
                or not 1 <= chunk_size <= MAX_AUDIO_CHUNK_SIZE
            ):
                return False

            source: NDArray[np.float64] = np.ndarray(
                destination.shape,
                dtype=np.float64,
                buffer=self._mapping,
                offset=_AUDIO_HEADER.size,
            )
            np.copyto(destination, source)
            return True
        finally:
            fcntl.flock(self._fd, fcntl.LOCK_UN)

    def close(self) -> None:
        """Release this process's handles without invalidating the other service."""
        self._mapping.close()
        os.close(self._fd)
