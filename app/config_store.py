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
    force_reindex: bool
    scan_profile: str
    max_scan_workers: int
    spotify_client_id: str
    spotify_client_secret: str
    spotify_redirect_uri: str
    jellyfin_server_url: str
    jellyfin_api_key: str
    jellyfin_user_id: str
    theme_name: str


class ConfigStore:
    def __init__(self, config_file: Path, logger: logging.Logger) -> None:
        self.config_file = config_file
        self.logger = logger.getChild("config")

    def defaults(self) -> AppConfig:
        return AppConfig(
            local_music_folder=str(get_default_local_music_folder()),
            spotify_csv_path=str(get_default_spotify_csv()),
            force_reindex=False,
            scan_profile="auto",
            max_scan_workers=0,
            spotify_client_id="",
            spotify_client_secret="",
            spotify_redirect_uri="http://127.0.0.1:8888/callback",
            jellyfin_server_url="",
            jellyfin_api_key="",
            jellyfin_user_id="",
            theme_name="palette_1",
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
                force_reindex=bool(raw.get("force_reindex", self.defaults().force_reindex)),
                scan_profile=str(raw.get("scan_profile", self.defaults().scan_profile)).strip().lower() or self.defaults().scan_profile,
                max_scan_workers=max(0, int(raw.get("max_scan_workers", self.defaults().max_scan_workers))),
                spotify_client_id=str(raw.get("spotify_client_id", self.defaults().spotify_client_id)).strip(),
                spotify_client_secret=str(raw.get("spotify_client_secret", self.defaults().spotify_client_secret)).strip(),
                spotify_redirect_uri=str(raw.get("spotify_redirect_uri", self.defaults().spotify_redirect_uri)).strip() or self.defaults().spotify_redirect_uri,
                jellyfin_server_url=str(raw.get("jellyfin_server_url", self.defaults().jellyfin_server_url)).strip(),
                jellyfin_api_key=str(raw.get("jellyfin_api_key", self.defaults().jellyfin_api_key)).strip(),
                jellyfin_user_id=str(raw.get("jellyfin_user_id", self.defaults().jellyfin_user_id)).strip(),
                theme_name=str(raw.get("theme_name", self.defaults().theme_name)).strip() or self.defaults().theme_name,
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
