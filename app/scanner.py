from __future__ import annotations

import json
import os
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
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


ProgressCallback = Callable[[int, int, str], None]
CancelCallback = Callable[[], bool]


class ScanCancelled(Exception):
    pass


@dataclass(frozen=True)
class FileCandidate:
    path: Path
    mtime_ns: int
    size: int


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


def _extract_track_record(file_path: Path) -> TrackRecord:
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

    return TrackRecord(track_name=track_name, artist=artist, album=album)


def _load_cache(cache_file: Path) -> dict:
    if not cache_file.exists():
        return {"entries": {}}
    try:
        return json.loads(cache_file.read_text(encoding="utf-8"))
    except Exception:
        return {"entries": {}}


def _save_cache(cache_file: Path, cache_data: dict) -> None:
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(cache_data, ensure_ascii=False, indent=2), encoding="utf-8")


def _is_network_fs_linux(path: Path) -> bool:
    network_fs = {
        "nfs",
        "nfs4",
        "cifs",
        "smb3",
        "smbfs",
        "fuse.sshfs",
        "sshfs",
        "davfs",
        "fuse.rclone",
    }

    try:
        mounts: list[tuple[Path, str]] = []
        with Path("/proc/mounts").open("r", encoding="utf-8") as f:
            for line in f:
                parts = line.split()
                if len(parts) < 3:
                    continue
                mount_path = Path(parts[1].replace("\\040", " "))
                mounts.append((mount_path, parts[2]))

        target = path.resolve()
        best_match_fs = ""
        best_len = -1
        for mount_path, fs_type in mounts:
            try:
                if str(target).startswith(str(mount_path)) and len(str(mount_path)) > best_len:
                    best_match_fs = fs_type
                    best_len = len(str(mount_path))
            except Exception:
                continue

        return best_match_fs in network_fs
    except Exception:
        return False


def _select_workers(root: Path, scan_profile: str, requested_workers: int | None) -> int:
    if requested_workers and requested_workers > 0:
        return requested_workers

    cpu = os.cpu_count() or 4
    profile = (scan_profile or "auto").strip().lower()

    if profile == "network":
        return min(6, max(2, cpu // 2))
    if profile == "local":
        return min(24, max(4, cpu * 2))

    if _is_network_fs_linux(root):
        return min(6, max(2, cpu // 2))
    return min(24, max(4, cpu * 2))


def _discover_audio_files(root: Path, should_cancel: CancelCallback | None = None) -> list[FileCandidate]:
    files: list[FileCandidate] = []

    # os.walk uses scandir internally and is usually faster/cheaper than rglob on large trees.
    for dirpath, _, filenames in os.walk(root):
        if should_cancel and should_cancel():
            raise ScanCancelled("Scan cancelled by user.")

        base = Path(dirpath)
        for name in filenames:
            if Path(name).suffix.lower() not in AUDIO_EXTENSIONS:
                continue

            file_path = base / name
            try:
                st = file_path.stat()
            except OSError:
                continue

            files.append(FileCandidate(path=file_path, mtime_ns=st.st_mtime_ns, size=st.st_size))

    return files


def scan_music_folder(
    root_path: str,
    on_progress: ProgressCallback | None = None,
    should_cancel: CancelCallback | None = None,
    cache_file: Path | None = None,
    use_cache: bool = True,
    max_workers: int | None = None,
    scan_profile: str = "auto",
) -> list[TrackRecord]:
    root = Path(root_path)
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(f"Music folder does not exist or is not a directory: {root_path}")

    all_audio_files = _discover_audio_files(root, should_cancel=should_cancel)
    total_files = len(all_audio_files)
    if on_progress:
        on_progress(0, total_files, "Preparing scan...")

    cache_data = {"entries": {}}
    cache_entries: dict[str, dict] = {}
    if cache_file is not None and use_cache:
        cache_data = _load_cache(cache_file)
        entries = cache_data.get("entries", {})
        if isinstance(entries, dict):
            cache_entries = entries

    records_by_path: dict[str, TrackRecord] = {}
    fresh_cache_entries: dict[str, dict] = {}
    to_parse: list[FileCandidate] = []
    completed = 0

    for candidate in all_audio_files:
        if should_cancel and should_cancel():
            raise ScanCancelled("Scan cancelled by user.")

        path_key = str(candidate.path)
        entry = cache_entries.get(path_key)

        if use_cache and entry and entry.get("mtime_ns") == candidate.mtime_ns and entry.get("size") == candidate.size:
            rec = TrackRecord(
                track_name=clean_text(entry.get("track_name", candidate.path.stem)),
                artist=clean_text(entry.get("artist", "")),
                album=clean_text(entry.get("album", "")),
            )
            records_by_path[path_key] = rec
            fresh_cache_entries[path_key] = entry
            completed += 1
            if on_progress:
                on_progress(completed, total_files, f"Cached: {candidate.path.name}")
            continue

        to_parse.append(candidate)

    if to_parse:
        workers = _select_workers(root, scan_profile=scan_profile, requested_workers=max_workers)
        executor = ThreadPoolExecutor(max_workers=max(1, workers))
        cancelled = False

        future_to_candidate: dict = {}
        submit_index = 0
        max_in_flight = max(4, workers * 3)

        while submit_index < len(to_parse) and len(future_to_candidate) < max_in_flight:
            candidate = to_parse[submit_index]
            future = executor.submit(_extract_track_record, candidate.path)
            future_to_candidate[future] = candidate
            submit_index += 1

        try:
            while future_to_candidate:
                if should_cancel and should_cancel():
                    cancelled = True
                    for pending in future_to_candidate:
                        pending.cancel()
                    executor.shutdown(wait=False, cancel_futures=True)
                    raise ScanCancelled("Scan cancelled by user.")

                done, _ = wait(future_to_candidate.keys(), timeout=0.25, return_when=FIRST_COMPLETED)
                if not done:
                    continue

                for future in done:
                    candidate = future_to_candidate.pop(future)
                    rec = future.result()

                    path_key = str(candidate.path)
                    records_by_path[path_key] = rec
                    fresh_cache_entries[path_key] = {
                        "mtime_ns": candidate.mtime_ns,
                        "size": candidate.size,
                        "track_name": rec.track_name,
                        "artist": rec.artist,
                        "album": rec.album,
                    }
                    completed += 1
                    if on_progress:
                        on_progress(completed, total_files, f"Scanning: {candidate.path.name}")

                while submit_index < len(to_parse) and len(future_to_candidate) < max_in_flight:
                    next_candidate = to_parse[submit_index]
                    next_future = executor.submit(_extract_track_record, next_candidate.path)
                    future_to_candidate[next_future] = next_candidate
                    submit_index += 1
        finally:
            if cancelled:
                executor.shutdown(wait=False, cancel_futures=True)
            else:
                executor.shutdown(wait=True, cancel_futures=True)

    if cache_file is not None:
        cache_data["entries"] = fresh_cache_entries
        _save_cache(cache_file, cache_data)

    records: list[TrackRecord] = []
    for candidate in all_audio_files:
        rec = records_by_path.get(str(candidate.path))
        if rec:
            records.append(rec)

    if on_progress:
        on_progress(total_files, total_files, "Scan complete")

    return records


def load_cached_records_for_root(root_path: str, cache_file: Path) -> list[TrackRecord]:
    root = Path(root_path)
    if not root.exists() or not root.is_dir() or not cache_file.exists():
        return []

    cache_data = _load_cache(cache_file)
    entries = cache_data.get("entries", {})
    if not isinstance(entries, dict):
        return []

    try:
        root_resolved = root.resolve()
    except Exception:
        root_resolved = root

    matched_paths: list[Path] = []
    mapped: dict[str, TrackRecord] = {}

    for path_str, entry in entries.items():
        if not isinstance(entry, dict):
            continue

        candidate = Path(path_str)
        try:
            candidate_resolved = candidate.resolve()
        except Exception:
            candidate_resolved = candidate

        try:
            is_under_root = candidate_resolved == root_resolved or root_resolved in candidate_resolved.parents
        except Exception:
            is_under_root = str(candidate_resolved).startswith(str(root_resolved))

        if not is_under_root:
            continue

        rec = TrackRecord(
            track_name=clean_text(entry.get("track_name", candidate.stem)),
            artist=clean_text(entry.get("artist", "")),
            album=clean_text(entry.get("album", "")),
        )
        matched_paths.append(candidate)
        mapped[str(candidate)] = rec

    matched_paths.sort(key=lambda p: str(p).casefold())
    return [mapped[str(p)] for p in matched_paths if str(p) in mapped]
