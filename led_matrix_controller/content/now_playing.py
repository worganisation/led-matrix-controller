"""Class for the creation, caching, and management of artwork images."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from re import Pattern
from re import compile as compile_regex
from threading import Thread
from time import monotonic
from typing import TYPE_CHECKING, Annotated, Any, ClassVar, Final, TypedDict

import aiohttp
import numpy as np
from content.base import GridView, StopType
from PIL import Image
from utils import const
from wg_utilities.loggers import get_streaming_logger

from .dynamic_content import DynamicContent
from .setting import ParameterSetting

if TYPE_CHECKING:
    from collections.abc import Generator

    from numpy.typing import DTypeLike, NDArray

LOGGER = get_streaming_logger(__name__)


class TrackMeta(TypedDict):
    """Type definition for the track metadata."""

    title: str | None
    album: str | None
    artist: str | None
    album_artwork_url: str | None


_INITIAL_TRACK_META: Final[TrackMeta] = {
    "title": "",
    "album": "",
    "artist": "",
    "album_artwork_url": "",
}


@dataclass(kw_only=True, slots=True)
class NowPlaying(DynamicContent):
    """Class for the creation, caching, and management of artwork images."""

    ARTWORK_DIRECTORY: ClassVar[Path] = (
        (
            Path("/var/cache")  # Script is run as root so this needs to be hardcoded
            if const.IS_PI
            else Path.home()
        )
        .joinpath(
            "led-matrix-controller",
            "artwork",
        )
        .resolve()
    )

    ALPHANUM_PATTERN: ClassVar[Pattern[str]] = compile_regex(r"[\W_]+")

    IS_OPAQUE: ClassVar[bool] = True

    track_metadata: Annotated[TrackMeta, ParameterSetting(icon="")] = field(
        default_factory=_INITIAL_TRACK_META.copy,
    )

    _current_image: tuple[tuple[Path, str], GridView] | None = field(
        default=None,
        init=False,
        repr=False,
        compare=False,
    )
    _download_thread: Thread | None = field(
        default=None,
        init=False,
        repr=False,
        compare=False,
    )
    _retry_after: tuple[tuple[Path, str], float] | None = field(
        default=None,
        init=False,
        repr=False,
        compare=False,
    )

    def get_content(self) -> GridView:
        """Return cached pixels immediately while a worker loads missing artwork."""
        if not (path := self.file_path) or not (url := self.artwork_uri):
            return self.pixels

        key = (path, url)
        if self._current_image is not None and self._current_image[0] == key:
            return self._current_image[1]

        if (self._download_thread is None or not self._download_thread.is_alive()) and (
            self._retry_after is None
            or self._retry_after[0] != key
            or monotonic() >= self._retry_after[1]
        ):
            self._download_thread = Thread(
                target=self._load_artwork,
                args=(key,),
                name="artwork-download",
                daemon=True,
            )
            self._download_thread.start()

        return self.pixels

    def _load_artwork(self, key: tuple[Path, str]) -> None:
        """Load one metadata snapshot without blocking rendering or mixing tracks."""
        path, url = key
        try:  # noqa: PLW0717 — Cache reads and download fallback share one failure/backoff path.
            try:
                pixels = np.load(path, allow_pickle=False)
            except (OSError, ValueError):
                pixels = asyncio.run(self._download(url))
                path.parent.mkdir(parents=True, exist_ok=True)
                np.save(path, pixels)

        except Exception:
            self._retry_after = (key, monotonic() + 30)
            LOGGER.exception("Failed to load artwork for %s", path)
        else:
            self._current_image = (key, pixels)

    async def _download(self, url: str) -> GridView:
        """Download and decode artwork with a bounded total request time."""
        async with (
            aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session,
            session.get(url) as response,
        ):
            response.raise_for_status()
            artwork_bytes = await response.read()

        with Image.open(BytesIO(artwork_bytes)) as image:
            return np.array(image.resize((self.width, self.height)).convert("RGBA"))

    def refresh_content(self) -> Generator[None, None, None]:
        """Refresh the content."""
        yield

        if None in self.track_metadata.values():
            self.stop(StopType.EXPIRED)
            self._current_image = None

    def zeros(self, *, dtype: DTypeLike = np.int_) -> NDArray[Any]:
        """Return a grid of zeros."""
        return np.zeros((self.height, self.width, 4), dtype=dtype)

    @property
    def artist_directory(self) -> str | None:
        """Artist name, with all non-alphanumeric characters removed.

        Returns:
            str: the artist name, with all non-alphanumeric characters removed
        """
        if not self.artist:
            return None

        return self.ALPHANUM_PATTERN.sub("", self.artist).lower()

    @property
    def filename(self) -> str | None:
        """Album name, with all non-alphanumeric characters removed.

        Returns:
            str: the filename of the artwork image
        """
        if not self.album:
            return None

        album = self.ALPHANUM_PATTERN.sub("", self.album).lower()
        artwork_id = sha256((self.artwork_uri or "").encode()).hexdigest()[:16]
        return f"{album}-{artwork_id}.npy"

    @property
    def file_path(self) -> Path | None:
        """Local path to the artwork image.

        Returns:
            Path: fully-qualified path to the artwork image
        """
        if not self.artist_directory or not self.filename:
            return None

        return self.ARTWORK_DIRECTORY / self.artist_directory / self.filename

    @property
    def album(self) -> str | None:
        """Album name."""
        return self.track_metadata.get("album")

    @property
    def artist(self) -> str | None:
        """Artist name."""
        return self.track_metadata.get("artist")

    @property
    def artwork_uri(self) -> str | None:
        """URL of the artwork."""
        return self.track_metadata.get("album_artwork_url")

    @property
    def title(self) -> str | None:
        """Title of the track."""
        return self.track_metadata.get("title")

    def __hash__(self) -> int:
        """Return the hash of the object."""
        return hash((self.artist, self.album, self.artwork_uri))

    def __str__(self) -> str:
        """Return the string representation of the object."""
        return self.__repr__()

    def __repr__(self) -> str:
        """Return the string representation of the object."""
        return (
            f"{self.__class__.__name__}({self.artist}, {self.album}, {self.artwork_uri})"
        )
