from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppDefaults:
    local_music_folder: Path
    spotify_csv: Path
    output_folder: Path


def _first_existing_dir(candidates: list[Path]) -> Path:
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return candidates[0]


def get_default_local_music_folder() -> Path:
    env_override = os.environ.get("MUSIC_LIBRARY_PATH", "").strip()
    if env_override:
        override_path = Path(env_override).expanduser()
        if override_path.is_dir():
            return override_path

    home = Path.home()
    if sys.platform.startswith("win"):
        candidates = [
            home / "Music",
            home / "OneDrive" / "Music",
        ]
    else:
        candidates = [
            Path("/media/share/Media/Music"),
            home / "Music",
            home / "music",
        ]

    return _first_existing_dir(candidates)


def get_default_spotify_csv() -> Path:
    return Path.home() / "Downloads" / "My Spotify Library.csv"


def get_default_output_folder() -> Path:
    return Path.cwd() / "Output"


def get_app_defaults() -> AppDefaults:
    return AppDefaults(
        local_music_folder=get_default_local_music_folder(),
        spotify_csv=get_default_spotify_csv(),
        output_folder=get_default_output_folder(),
    )


def open_in_file_explorer(target_path: Path) -> None:
    if sys.platform.startswith("win"):
        os.startfile(str(target_path))
        return

    if sys.platform.startswith("linux"):
        opener = shutil.which("xdg-open")
        if opener is None:
            raise RuntimeError("xdg-open is not available on this Linux system.")
        subprocess.Popen([opener, str(target_path)])
        return

    if sys.platform == "darwin":
        subprocess.Popen(["open", str(target_path)])
        return

    raise RuntimeError("Opening file explorer is not supported on this platform.")
