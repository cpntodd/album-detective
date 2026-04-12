from __future__ import annotations

import csv
from pathlib import Path

from .models import AlbumArtistRecord, TrackRecord


def write_track_csv(file_path: str | Path, records: list[TrackRecord]) -> None:
    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Track name", "Artist", "Album"])
        for rec in records:
            writer.writerow([rec.track_name, rec.artist, rec.album])


def read_spotify_csv(file_path: str | Path) -> list[TrackRecord]:
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Spotify CSV not found: {file_path}")

    cleaned: list[TrackRecord] = []
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)

        for row in reader:
            track_name = (row.get("Track name") or "").strip()
            # Spotify export commonly uses "Artist name".
            artist = (row.get("Artist") or row.get("Artist name") or "").strip()
            album = (row.get("Album") or "").strip()

            cleaned.append(
                TrackRecord(
                    track_name=track_name,
                    artist=artist,
                    album=album,
                )
            )

    return cleaned


def write_album_artist_csv(file_path: str | Path, records: list[AlbumArtistRecord]) -> None:
    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Artist", "Album"])
        for rec in records:
            writer.writerow([rec.artist, rec.album])
