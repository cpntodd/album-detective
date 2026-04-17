from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Callable

from .library_indexer import discover_audio_files, extract_audio_metadata

ProgressCallback = Callable[[int, int, str], None]
CancelCallback = Callable[[], bool]


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
    metadata = extract_audio_metadata(path)

    return {
        "Track name": metadata.track_name,
        "Artist": metadata.artist,
        "Album": metadata.album,
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

    candidates = [
        item.path
        for item in discover_audio_files(
            root,
            should_cancel=should_cancel,
            cancel_exception=RuntimeError,
            cancel_message="Cancelled",
            on_diagnostic=None,
        )
    ]

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
