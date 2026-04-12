from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TrackRecord:
    track_name: str
    artist: str
    album: str


@dataclass(frozen=True)
class AlbumArtistRecord:
    artist: str
    album: str
