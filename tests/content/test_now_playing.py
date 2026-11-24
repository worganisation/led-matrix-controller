"""Artwork loading must not hold up display frames."""

from __future__ import annotations

from asyncio import to_thread
from threading import Event
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import numpy as np
import pytest
from content.now_playing import NowPlaying

if TYPE_CHECKING:
    from pathlib import Path

    from content.base import GridView


@pytest.fixture
def artwork(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> NowPlaying:
    """Build a player with an isolated cache and registry ID."""
    monkeypatch.setattr(NowPlaying, "ARTWORK_DIRECTORY", tmp_path)
    return NowPlaying(
        id_override=str(tmp_path),
        track_metadata={
            "album": "Album",
            "artist": "Artist",
            "title": "Title",
            "album_artwork_url": "https://example.com/first.png",
        },
    )


def test_download_does_not_block_frames_or_display_stale_track(
    artwork: NowPlaying,
) -> None:
    """A pending old track download cannot delay frames or become the new artwork."""
    started = Event()
    release = Event()
    pixels = np.ones((64, 64, 4), dtype=np.int_)

    async def download(_url: str) -> GridView:
        started.set()
        assert await to_thread(release.wait, 5)
        return pixels

    with patch.object(NowPlaying, "_download", side_effect=download) as loader:
        try:
            assert artwork.get_content() is artwork.pixels
            assert started.wait(5)
            for _ in range(10):
                assert artwork.get_content() is artwork.pixels
            loader.assert_called_once()
            artwork.track_metadata["album_artwork_url"] = "https://example.com/new.png"
        finally:
            release.set()
            assert artwork._download_thread is not None
            artwork._download_thread.join(5)

        # Keep the next worker from starting while examining the stale result.
        with patch("content.now_playing.Thread"):
            assert artwork.get_content() is artwork.pixels


def test_failed_download_backs_off(artwork: NowPlaying) -> None:
    """Repeated render frames cannot repeatedly retry a failed server."""
    with patch.object(
        NowPlaying,
        "_download",
        new=AsyncMock(side_effect=OSError),
    ) as loader:
        artwork.get_content()
        assert artwork._download_thread is not None
        artwork._download_thread.join(5)
        for _ in range(10):
            artwork.get_content()

        loader.assert_called_once()


def test_cached_artwork_is_loaded_without_http(artwork: NowPlaying) -> None:
    """The worker uses persisted artwork and returns the same array on later frames."""
    assert artwork.file_path is not None
    artwork.file_path.parent.mkdir(parents=True)
    pixels = np.ones((64, 64, 4), dtype=np.int_)
    np.save(artwork.file_path, pixels)

    with patch.object(NowPlaying, "_download") as loader:
        artwork.get_content()
        assert artwork._download_thread is not None
        artwork._download_thread.join(5)
        loaded = artwork.get_content()

        np.testing.assert_array_equal(loaded, pixels)
        assert artwork.get_content() is loaded
        loader.assert_not_called()


def test_resize_cached_artwork(artwork: NowPlaying) -> None:
    """Resize the current track and keep it within the display bounds.

    Args:
        artwork: Player with an isolated artwork cache.
    """
    assert artwork.file_path is not None
    source = np.full((64, 64, 4), 255, dtype=np.uint8)
    artwork._current_image = ((artwork.file_path, artwork.artwork_uri or ""), source)
    artwork.size = 16

    frame = artwork.get_content()
    assert frame.shape == (16, 16, 4)
    assert np.all(frame == 255)
    assert artwork.get_content() is frame

    artwork.x_pos = artwork.y_pos = 48
    artwork.size = 64
    assert artwork.get_content() is source
    assert artwork.position == (0, 0)
