from __future__ import annotations

from pathlib import Path
from typing import Callable

from mutagen import File as MutagenFile

from .models import TrackRecord
from .normalization import clean_text

AUDIO_EXTENSIONS = {
    ".mp3",
    ".flac",
    ".m4a",
    ".aac",
    ".ogg",
    ".opus",
    ".wav",
    ".wma",
    ".aiff",
    ".aif",
    ".ape",
    ".alac",
}


ProgressCallback = Callable[[str], None]


def _first_tag(tags: dict, *keys: str) -> str:
    for key in keys:
        value = tags.get(key)
        if value:
            if isinstance(value, list):
                return clean_text(value[0])
            return clean_text(str(value))
    return ""


def _infer_from_path(path: Path) -> tuple[str, str]:
    # Typical pattern: .../<Artist>/<Album>/<Track.ext>
    parts = path.parts
    if len(parts) >= 3:
        album = clean_text(parts[-2])
        artist = clean_text(parts[-3])
        return artist, album
    return "", ""


def scan_music_folder(root_path: str, on_progress: ProgressCallback | None = None) -> list[TrackRecord]:
    root = Path(root_path)
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(f"Music folder does not exist or is not a directory: {root_path}")

    records: list[TrackRecord] = []

    for file_path in root.rglob("*"):
        if not file_path.is_file() or file_path.suffix.lower() not in AUDIO_EXTENSIONS:
            continue

        if on_progress:
            on_progress(f"Scanning: {file_path.name}")

        track_name = clean_text(file_path.stem)
        artist = ""
        album = ""

        try:
            audio = MutagenFile(file_path, easy=True)
            tags = audio.tags if audio else None
            if tags:
                artist = _first_tag(tags, "artist", "albumartist")
                album = _first_tag(tags, "album")
                track_name = _first_tag(tags, "title") or track_name
        except Exception:
            # Keep scanning even if a file has bad metadata.
            pass

        if not artist or not album:
            inferred_artist, inferred_album = _infer_from_path(file_path)
            artist = artist or inferred_artist
            album = album or inferred_album

        records.append(
            TrackRecord(
                track_name=track_name,
                artist=artist,
                album=album,
            )
        )

    return records
