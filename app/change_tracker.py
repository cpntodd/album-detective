"""File change tracking for incremental/delta scanning.

Tracks library changes using file metadata snapshots (mtime_ns, size).
Enables efficient re-verification of only changed files instead of
full library re-scan.

Similar to HOI4StudioGUI's FileChangeTracker, but adapted for audio libraries.
"""

import json
import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# File signature: (mtime_ns, size) tuple
FileSignature = Tuple[int, int]


@dataclass
class FileChangeSnapshot:
    """Snapshot of file metadata for change detection."""
    path_str: str
    mtime_ns: int
    size: int
    
    def matches(self, other: "FileChangeSnapshot") -> bool:
        """Check if file signature matches (unchanged)."""
        return self.mtime_ns == other.mtime_ns and self.size == other.size


class LibraryChangeTracker:
    """Tracks changes in audio library across scan sessions.
    
    Stores snapshot of (mtime_ns, size) for each file.
    Detects added/modified/removed files by comparing snapshots.
    
    Usage:
        tracker = LibraryChangeTracker(root_path)
        changes = tracker.detect_changes(current_files)
        # changes = {"added": [...], "modified": [...], "removed": [...]}
        tracker.save_snapshot()  # Persist for next session
    """
    
    def __init__(self, root_path: Path, snapshot_path: Optional[Path] = None):
        self.root_path = Path(root_path)
        
        # Default snapshot location: .album_detective_cache/scan_snapshot.json
        if snapshot_path is None:
            snapshot_path = self.root_path / ".album_detective_cache" / "scan_snapshot.json"
        
        self.snapshot_path = Path(snapshot_path)
        self._current_snapshot: Dict[str, FileChangeSnapshot] = {}
        self._previous_snapshot: Dict[str, FileChangeSnapshot] = {}
        self._lock = threading.Lock()
        
        self._load_previous_snapshot()
    
    def _load_previous_snapshot(self) -> None:
        """Load previous snapshot from disk."""
        try:
            if self.snapshot_path.exists():
                with open(self.snapshot_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        for rel_path_str, metadata in data.items():
                            if isinstance(metadata, dict):
                                snap = FileChangeSnapshot(
                                    path_str=rel_path_str,
                                    mtime_ns=int(metadata.get("mtime_ns", 0)),
                                    size=int(metadata.get("size", 0)),
                                )
                                self._previous_snapshot[rel_path_str] = snap
                logger.debug(f"Loaded snapshot with {len(self._previous_snapshot)} entries")
        except Exception as exc:
            logger.warning(f"Failed to load snapshot: {exc}")
    
    def _save_snapshot(self) -> None:
        """Save current snapshot to disk."""
        try:
            self.snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            
            data = {}
            for rel_path_str, snap in self._current_snapshot.items():
                data[rel_path_str] = {
                    "mtime_ns": snap.mtime_ns,
                    "size": snap.size,
                }
            
            with open(self.snapshot_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            
            logger.debug(f"Saved snapshot with {len(self._current_snapshot)} entries")
        except Exception as exc:
            logger.warning(f"Failed to save snapshot: {exc}")
    
    def detect_changes(self, current_files: List[Path]) -> Dict[str, List[Path]]:
        """Detect added/modified/removed files by comparing snapshots.
        
        Args:
            current_files: List of current audio file paths
        
        Returns:
            Dict with keys:
                "added": List[Path] - Files not in previous snapshot
                "modified": List[Path] - Files with changed mtime or size
                "removed": List[Path] - Files in previous snapshot but not current
        """
        with self._lock:
            # Build current snapshot
            self._current_snapshot = {}
            current_set: Set[str] = set()
            
            for file_path in current_files:
                try:
                    rel_path = file_path.relative_to(self.root_path)
                    rel_path_str = str(rel_path)
                    current_set.add(rel_path_str)
                    
                    stat_info = file_path.stat()
                    snap = FileChangeSnapshot(
                        path_str=rel_path_str,
                        mtime_ns=stat_info.st_mtime_ns,
                        size=stat_info.st_size,
                    )
                    self._current_snapshot[rel_path_str] = snap
                except Exception as exc:
                    logger.warning(f"Failed to stat {file_path}: {exc}")
            
            # Detect changes
            added: List[Path] = []
            modified: List[Path] = []
            removed: List[Path] = []
            
            # Added and modified
            for rel_path_str, curr_snap in self._current_snapshot.items():
                prev_snap = self._previous_snapshot.get(rel_path_str)
                file_path = self.root_path / rel_path_str
                
                if prev_snap is None:
                    # New file
                    added.append(file_path)
                elif not curr_snap.matches(prev_snap):
                    # File changed
                    modified.append(file_path)
            
            # Removed
            for rel_path_str in self._previous_snapshot:
                if rel_path_str not in current_set:
                    file_path = self.root_path / rel_path_str
                    removed.append(file_path)
            
            logger.debug(f"Changes detected: +{len(added)} ~{len(modified)} -{len(removed)}")
            
            return {
                "added": added,
                "modified": modified,
                "removed": removed,
            }
    
    def save_snapshot(self) -> None:
        """Persist current snapshot for next session."""
        with self._lock:
            self._save_snapshot()
    
    def clear_history(self) -> None:
        """Clear both current and previous snapshots."""
        with self._lock:
            self._current_snapshot.clear()
            self._previous_snapshot.clear()
            if self.snapshot_path.exists():
                try:
                    self.snapshot_path.unlink()
                except Exception as exc:
                    logger.warning(f"Failed to delete snapshot file: {exc}")
    
    def get_stats(self) -> Dict[str, int]:
        """Return snapshot statistics."""
        with self._lock:
            return {
                "current_files": len(self._current_snapshot),
                "previous_files": len(self._previous_snapshot),
                "snapshot_path": str(self.snapshot_path),
            }


class LibraryHasher:
    """Compute hash of audio library for signature-based caching.
    
    Used to detect if library has changed (for report-level caching).
    Hash includes: number of files, total size, list of artist|album pairs.
    """
    
    @staticmethod
    def compute_library_hash(audio_files: List[Path]) -> str:
        """Compute library hash from audio files.
        
        Args:
            audio_files: List of audio file paths
        
        Returns:
            Hexadecimal hash string
        """
        import hashlib
        
        file_sigs = []
        for file_path in sorted(audio_files):
            try:
                stat_info = file_path.stat()
                # Include path, size, and mtime in hash
                sig = f"{file_path.name}:{stat_info.st_size}:{stat_info.st_mtime_ns}"
                file_sigs.append(sig)
            except Exception:
                continue
        
        combined = "\n".join(file_sigs)
        return hashlib.sha256(combined.encode()).hexdigest()
    
    @staticmethod
    def compute_metadata_hash(artist: str, album: str, track: str) -> str:
        """Compute hash of audio metadata for signature.
        
        Args:
            artist: Artist name
            album: Album name
            track: Track title
        
        Returns:
            Hexadecimal hash string
        """
        import hashlib
        
        combined = f"{artist}|{album}|{track}"
        return hashlib.sha256(combined.encode()).hexdigest()
