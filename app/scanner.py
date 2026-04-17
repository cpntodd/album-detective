from __future__ import annotations

import json
import os
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from .change_tracker import LibraryChangeTracker
from .library_indexer import discover_audio_files, extract_audio_metadata
from .models import TrackRecord
from .normalization import clean_text


ProgressCallback = Callable[[int, int, str], None]
CancelCallback = Callable[[], bool]
DiagnosticCallback = Callable[[str], None]


class ScanCancelled(Exception):
    pass


@dataclass(frozen=True)
class FileCandidate:
    path: Path
    mtime_ns: int
    size: int


def _extract_track_record(file_path: Path) -> TrackRecord:
    metadata = extract_audio_metadata(file_path)
    return TrackRecord(track_name=metadata.track_name, artist=metadata.artist, album=metadata.album)


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
        # Network I/O benefits from 8-16 threads for metadata extraction (I/O-bound).
        return min(16, max(8, cpu * 2))
    if profile == "local":
        return min(24, max(4, cpu * 2))

    if _is_network_fs_linux(root):
        # Auto-detected network FS: use network thread settings for parallelism.
        return min(16, max(8, cpu * 2))
    return min(24, max(4, cpu * 2))


def scan_music_folder(
    root_path: str,
    on_progress: ProgressCallback | None = None,
    on_diagnostic: DiagnosticCallback | None = None,
    should_cancel: CancelCallback | None = None,
    cache_file: Path | None = None,
    use_cache: bool = True,
    max_workers: int | None = None,
    scan_profile: str = "auto",
    use_change_tracking: bool = True,
) -> list[TrackRecord]:
    """Scan music folder with optional change tracking for delta scans.
    
    Args:
        root_path: Path to music folder
        on_progress: Progress callback
        on_diagnostic: Diagnostic callback
        should_cancel: Cancellation callback
        cache_file: Cache file path
        use_cache: If True, use file-level cache
        max_workers: Max worker threads
        scan_profile: Scan profile ("auto", "local", "network")
        use_change_tracking: If True, only scan changed files (delta scan)
    
    Returns:
        List of TrackRecord objects
    """
    root = Path(root_path)
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(f"Music folder does not exist or is not a directory: {root_path}")

    all_audio_files = [
        FileCandidate(path=item.path, mtime_ns=item.mtime_ns, size=item.size)
        for item in discover_audio_files(
            root,
            should_cancel=should_cancel,
            cancel_exception=ScanCancelled,
            cancel_message="Scan cancelled by user.",
            on_diagnostic=on_diagnostic,
        )
    ]
    total_files = len(all_audio_files)
    if on_progress:
        on_progress(0, total_files, "Preparing scan...")
    if on_diagnostic:
        cache_state = "enabled" if (use_cache and cache_file is not None) else "disabled"
        delta_mode = "enabled" if use_change_tracking else "disabled"
        on_diagnostic(f"index mode: cache={cache_state}, delta={delta_mode}, profile={scan_profile}")

    # Initialize change tracker for delta scanning
    change_tracker = None
    candidates_to_scan = all_audio_files
    
    if use_change_tracking:
        try:
            change_tracker = LibraryChangeTracker(root_path=root)
            file_paths = [c.path for c in all_audio_files]
            changes = change_tracker.detect_changes(file_paths)
            
            added = set(str(p) for p in changes.get("added", []))
            modified = set(str(p) for p in changes.get("modified", []))
            removed = set(str(p) for p in changes.get("removed", []))
            
            # Only need to scan added/modified files; removed are naturally not in current list
            to_scan_paths = added | modified
            candidates_to_scan = [c for c in all_audio_files if str(c.path) in to_scan_paths]
            
            if on_diagnostic:
                on_diagnostic(f"delta scan: +{len(added)} ~{len(modified)} -{len(removed)}")
        except Exception as exc:
            if on_diagnostic:
                on_diagnostic(f"delta tracking disabled: {exc}")
            change_tracker = None

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
    cached_hits = 0

    for candidate in candidates_to_scan:
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
            cached_hits += 1
            if on_progress:
                on_progress(completed, total_files, f"Cached: {candidate.path.name}")
            continue

        to_parse.append(candidate)

    if on_diagnostic:
        on_diagnostic(f"index pass: cached={cached_hits}, fresh={len(to_parse)}, total={total_files}")

    if to_parse:
        workers = _select_workers(root, scan_profile=scan_profile, requested_workers=max_workers)
        if on_diagnostic:
            on_diagnostic(f"index workers: {workers} threads")
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

    # Save change tracker snapshot for next session
    if change_tracker is not None:
        try:
            change_tracker.save_snapshot()
        except Exception as exc:
            if on_diagnostic:
                on_diagnostic(f"Failed to save change tracking snapshot: {exc}")

    # For delta scan mode, also include cached records from non-changed files
    if use_change_tracking and change_tracker is not None:
        for candidate in all_audio_files:
            path_key = str(candidate.path)
            if path_key not in records_by_path:
                entry = cache_entries.get(path_key)
                if entry and entry.get("mtime_ns") == candidate.mtime_ns and entry.get("size") == candidate.size:
                    rec = TrackRecord(
                        track_name=clean_text(entry.get("track_name", candidate.path.stem)),
                        artist=clean_text(entry.get("artist", "")),
                        album=clean_text(entry.get("album", "")),
                    )
                    records_by_path[path_key] = rec

    records: list[TrackRecord] = []
    for candidate in all_audio_files:
        rec = records_by_path.get(str(candidate.path))
        if rec:
            records.append(rec)

    if on_progress:
        on_progress(total_files, total_files, "Scan complete")
    if on_diagnostic:
        on_diagnostic(f"index done: cached={cached_hits}, parsed={len(to_parse)}")

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
