from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from mutagen import File as MutagenFile

from .normalization import clean_text

CancelCallback = Callable[[], bool]

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


@dataclass(frozen=True)
class AudioFileCandidate:
    path: Path
    mtime_ns: int
    size: int


@dataclass(frozen=True)
class AudioMetadata:
    track_name: str
    artist: str
    album: str
    genre: str


def _first_tag(tags: dict, *keys: str) -> str:
    for key in keys:
        value = tags.get(key)
        if not value:
            continue
        if isinstance(value, list):
            return clean_text(str(value[0]))
        return clean_text(str(value))
    return ""


def _infer_artist_album(path: Path) -> tuple[str, str]:
    # Typical pattern: .../<Artist>/<Album>/<Track.ext>
    parts = path.parts
    if len(parts) >= 3:
        artist = clean_text(parts[-3])
        album = clean_text(parts[-2])
        return artist, album
    return "", ""


def _raise_if_cancelled(
    should_cancel: CancelCallback | None,
    *,
    cancel_exception: type[Exception],
    cancel_message: str,
) -> None:
    if should_cancel and should_cancel():
        raise cancel_exception(cancel_message)


def discover_audio_files(
    root: Path,
    *,
    should_cancel: CancelCallback | None = None,
    cancel_exception: type[Exception] = RuntimeError,
    cancel_message: str = "Scan cancelled",
) -> list[AudioFileCandidate]:
    files: list[AudioFileCandidate] = []

    # os.walk uses scandir internally and is efficient on large trees.
    for dirpath, _, filenames in os.walk(root):
        _raise_if_cancelled(
            should_cancel,
            cancel_exception=cancel_exception,
            cancel_message=cancel_message,
        )

        base = Path(dirpath)
        for name in filenames:
            if Path(name).suffix.lower() not in AUDIO_EXTENSIONS:
                continue

            file_path = base / name
            try:
                st = file_path.stat()
            except OSError:
                continue

            files.append(AudioFileCandidate(path=file_path, mtime_ns=st.st_mtime_ns, size=st.st_size))

    return files


def extract_audio_metadata(file_path: Path) -> AudioMetadata:
    track_name = clean_text(file_path.stem)
    artist = ""
    album = ""
    genre = ""

    try:
        audio = MutagenFile(file_path, easy=True)
        tags = audio.tags if audio else None
        if tags:
            artist = _first_tag(tags, "artist", "albumartist")
            album = _first_tag(tags, "album")
            track_name = _first_tag(tags, "title") or track_name
            genre = _first_tag(tags, "genre")
    except Exception:
        # Keep scanning even if a file has malformed metadata.
        pass

    if not artist or not album:
        inferred_artist, inferred_album = _infer_artist_album(file_path)
        artist = artist or inferred_artist
        album = album or inferred_album

    return AudioMetadata(track_name=track_name, artist=artist, album=album, genre=genre)
