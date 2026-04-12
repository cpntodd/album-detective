from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import requests


MUSICBRAINZ_SEARCH_URL: Final[str] = "https://musicbrainz.org/ws/2/release/"
COVER_ART_ARCHIVE_URL: Final[str] = "https://coverartarchive.org/release/{mbid}/front-250"
DEFAULT_USER_AGENT: Final[str] = "compare-app/1.0 ( https://github.com/cpntodd/compare )"


@dataclass(frozen=True)
class ArtworkResolution:
    mbid: str
    image_path: Path


class ArtworkResolver:
    def __init__(
        self,
        cache_root: Path,
        *,
        use_cache: bool = True,
        timeout: int = 10,
        logger: logging.Logger | None = None,
    ) -> None:
        self.cache_root = cache_root
        self.use_cache = use_cache
        self.timeout = timeout
        self.logger = logger or logging.getLogger("compare_app.artwork")
        self.cache_dir = self.cache_root / "artwork"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/json",
                "User-Agent": DEFAULT_USER_AGENT,
            }
        )
        self._resolved: dict[tuple[str, str], ArtworkResolution | None] = {}

    def resolve(self, artist: str, album: str) -> ArtworkResolution | None:
        normalized_artist = artist.strip()
        normalized_album = album.strip()
        if not normalized_artist or not normalized_album:
            return None

        key = (normalized_artist.casefold(), normalized_album.casefold())
        if key in self._resolved:
            return self._resolved[key]

        try:
            mbid = self._lookup_release_mbid(normalized_artist, normalized_album)
            if not mbid:
                self._resolved[key] = None
                return None

            cached_image = self.cache_dir / f"{mbid}.jpg"
            if self.use_cache and cached_image.exists() and cached_image.stat().st_size > 0:
                resolution = ArtworkResolution(mbid=mbid, image_path=cached_image)
                self._resolved[key] = resolution
                return resolution

            image_bytes = self._fetch_cover_art(mbid)
            if not image_bytes:
                self._resolved[key] = None
                return None

            cached_image.write_bytes(image_bytes)
            resolution = ArtworkResolution(mbid=mbid, image_path=cached_image)
            self._resolved[key] = resolution
            return resolution
        except Exception:
            self.logger.exception("Artwork resolution failed for artist=%s album=%s", normalized_artist, normalized_album)
            self._resolved[key] = None
            return None

    def _lookup_release_mbid(self, artist: str, album: str) -> str | None:
        response = self.session.get(
            MUSICBRAINZ_SEARCH_URL,
            params={
                "query": f"artist:{artist} AND release:{album}",
                "fmt": "json",
                "limit": 1,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()

        payload = response.json()
        releases = payload.get("releases")
        if not isinstance(releases, list) or not releases:
            return None

        first_release = releases[0]
        mbid = str(first_release.get("id") or "").strip()
        return mbid or None

    def _fetch_cover_art(self, mbid: str) -> bytes | None:
        response = self.session.get(
            COVER_ART_ARCHIVE_URL.format(mbid=mbid),
            timeout=self.timeout,
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.content or None
