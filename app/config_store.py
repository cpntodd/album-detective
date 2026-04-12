from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

from .platform_support import get_default_local_music_folder, get_default_spotify_csv


@dataclass(frozen=True)
class AppConfig:
    local_music_folder: str
    spotify_csv_path: str


class ConfigStore:
    def __init__(self, config_file: Path, logger: logging.Logger) -> None:
        self.config_file = config_file
        self.logger = logger.getChild("config")

    def defaults(self) -> AppConfig:
        return AppConfig(
            local_music_folder=str(get_default_local_music_folder()),
            spotify_csv_path=str(get_default_spotify_csv()),
        )

    def load(self) -> AppConfig:
        if not self.config_file.exists():
            cfg = self.defaults()
            self.save(cfg)
            return cfg

        try:
            raw = json.loads(self.config_file.read_text(encoding="utf-8"))
            return AppConfig(
                local_music_folder=str(raw.get("local_music_folder", "")).strip() or self.defaults().local_music_folder,
                spotify_csv_path=str(raw.get("spotify_csv_path", "")).strip() or self.defaults().spotify_csv_path,
            )
        except Exception:
            self.logger.exception("Failed to read config, restoring defaults")
            cfg = self.defaults()
            self.save(cfg)
            return cfg

    def save(self, config: AppConfig) -> None:
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        self.config_file.write_text(json.dumps(asdict(config), indent=2), encoding="utf-8")
        self.logger.info("Config saved to %s", self.config_file)
