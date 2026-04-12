from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Callable

from mutagen import File as MutagenFile


ProgressCallback = Callable[[int, int, str], None]
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


def _first_tag(tags: dict, *keys: str) -> str:
    for key in keys:
        value = tags.get(key)
        if not value:
            continue
        if isinstance(value, list):
            return str(value[0]).strip()
        return str(value).strip()
    return ""


def _fast_file_hash(path: Path, mtime_ns: int, size: int) -> str:
    """Fast fingerprint: size + mtime + partial bytes from head/tail."""
    h = hashlib.sha1()
    h.update(str(size).encode("utf-8"))
    h.update(b"|")
    h.update(str(mtime_ns).encode("utf-8"))

    read_size = 65536
    try:
        with path.open("rb") as f:
            head = f.read(read_size)
            h.update(head)
            if size > read_size:
                f.seek(max(0, size - read_size))
                tail = f.read(read_size)
                h.update(tail)
    except OSError:
        pass

    return h.hexdigest()


def _extract_metadata(path: Path) -> dict:
    track_name = path.stem
    artist = ""
    album = ""

    try:
        audio = MutagenFile(path, easy=True)
        tags = audio.tags if audio else None
        if tags:
            track_name = _first_tag(tags, "title") or track_name
            artist = _first_tag(tags, "artist", "albumartist")
            album = _first_tag(tags, "album")
    except Exception:
        pass

    if not artist or not album:
        parts = path.parts
        if len(parts) >= 3:
            artist = artist or parts[-3]
            album = album or parts[-2]

    return {
        "Track name": track_name.strip(),
        "Artist": artist.strip(),
        "Album": album.strip(),
        "Path": str(path),
    }


def scan_nas_cached(
    root_path: str,
    cache_dir: Path,
    on_progress: ProgressCallback | None = None,
    should_cancel: CancelCallback | None = None,
) -> list[dict]:
    root = Path(root_path)
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(f"NAS path not found or not a directory: {root_path}")

    cache_dir.mkdir(parents=True, exist_ok=True)

    candidates: list[Path] = []
    for dirpath, _, filenames in os.walk(root):
        if should_cancel and should_cancel():
            raise RuntimeError("Cancelled")
        base = Path(dirpath)
        for name in filenames:
            if Path(name).suffix.lower() in AUDIO_EXTENSIONS:
                candidates.append(base / name)

    candidates.sort(key=lambda p: str(p).casefold())
    total = len(candidates)

    rows: list[dict] = []

    for i, path in enumerate(candidates, start=1):
        if should_cancel and should_cancel():
            raise RuntimeError("Cancelled")

        try:
            stat = path.stat()
        except OSError:
            continue

        file_hash = _fast_file_hash(path, stat.st_mtime_ns, stat.st_size)
        cache_file = cache_dir / f"{file_hash}.json"

        if cache_file.exists():
            try:
                cached = json.loads(cache_file.read_text(encoding="utf-8"))
                row = {
                    "Track name": str(cached.get("Track name") or "").strip(),
                    "Artist": str(cached.get("Artist") or "").strip(),
                    "Album": str(cached.get("Album") or "").strip(),
                    "Path": str(cached.get("Path") or str(path)),
                }
            except Exception:
                row = _extract_metadata(path)
                cache_file.write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            row = _extract_metadata(path)
            cache_file.write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8")

        rows.append(row)

        if on_progress:
            on_progress(i, total, f"NAS cached scan: {path.name}")

    return rows
