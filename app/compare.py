from __future__ import annotations

from .models import AlbumArtistRecord, TrackRecord
from .normalization import clean_text, norm_album_key, norm_key


def unique_album_artist(records: list[TrackRecord]) -> list[AlbumArtistRecord]:
    seen: set[tuple[str, str]] = set()
    unique: list[AlbumArtistRecord] = []

    for rec in records:
        artist = clean_text(rec.artist)
        album = clean_text(rec.album)
        if not artist or not album:
            continue

        key = (norm_key(artist), norm_album_key(album))
        if key in seen:
            continue
        seen.add(key)
        unique.append(AlbumArtistRecord(artist=artist, album=album))

    unique.sort(key=lambda r: (norm_key(r.artist), norm_album_key(r.album)))
    return unique


def spotify_not_owned(local_tracks: list[TrackRecord], spotify_tracks: list[TrackRecord]) -> list[AlbumArtistRecord]:
    local_pairs = unique_album_artist(local_tracks)
    spotify_pairs = unique_album_artist(spotify_tracks)

    owned_keys = {(norm_key(r.artist), norm_album_key(r.album)) for r in local_pairs}

    missing = [
        rec
        for rec in spotify_pairs
        if (norm_key(rec.artist), norm_album_key(rec.album)) not in owned_keys
    ]

    missing.sort(key=lambda r: (norm_key(r.artist), norm_album_key(r.album)))
    return missing
