from __future__ import annotations

import logging
import threading
import time
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


MUSICBRAINZ_SEARCH_URL: Final[str] = "https://musicbrainz.org/ws/2/release/"
COVER_ART_ARCHIVE_URL: Final[str] = "https://coverartarchive.org/release/{mbid}/front-250"
DEFAULT_USER_AGENT: Final[str] = "album-detective/1.0 ( https://github.com/cpntodd/album-detective )"


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
        min_request_interval: float = 0.2,
        logger: logging.Logger | None = None,
    ) -> None:
        self.cache_root = cache_root
        self.use_cache = use_cache
        self.timeout = timeout
        self.min_request_interval = max(0.0, min_request_interval)
        self.logger = logger or logging.getLogger("compare_app.artwork")
        self.cache_dir = self.cache_root / "artwork"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.home_cache_dir = Path.home() / "cache" / "artwork"
        self.home_cache_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/json",
                "User-Agent": DEFAULT_USER_AGENT,
            }
        )
        retry = Retry(
            total=3,
            read=3,
            connect=3,
            backoff_factor=0.4,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET",),
            respect_retry_after_header=True,
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("https://", adapter)
        self._resolved: dict[tuple[str, str], ArtworkResolution | None] = {}
        self._inflight: dict[tuple[str, str], threading.Event] = {}
        self._cache_lock = threading.Lock()
        self._request_lock = threading.Lock()
        self._next_request_time = 0.0

    def _slug(self, value: str) -> str:
        collapsed = re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")
        return collapsed or "unknown"

    def _cache_key_stems(self, artist: str, album: str) -> tuple[str, str]:
        plain_stem = f"{self._slug(artist)}__{self._slug(album)}"
        hash_stem = hashlib.sha1(f"{artist.casefold()}::{album.casefold()}".encode("utf-8")).hexdigest()
        return plain_stem, hash_stem

    def _find_by_stem(self, cache_dir: Path, stem: str) -> Path | None:
        for ext in ("jpg", "jpeg", "png", "webp"):
            candidate = cache_dir / f"{stem}.{ext}"
            if candidate.exists() and candidate.stat().st_size > 0:
                return candidate
        return None

    def _find_precached_image(self, artist: str, album: str) -> Path | None:
        plain_stem, hash_stem = self._cache_key_stems(artist, album)
        for cache_dir in (self.cache_dir, self.home_cache_dir):
            for stem in (plain_stem, hash_stem):
                found = self._find_by_stem(cache_dir, stem)
                if found is not None:
                    return found
        return None

    def _find_mbid_cached_image(self, mbid: str) -> Path | None:
        for cache_dir in (self.cache_dir, self.home_cache_dir):
            for ext in ("jpg", "jpeg", "png", "webp"):
                candidate = cache_dir / f"{mbid}.{ext}"
                if candidate.exists() and candidate.stat().st_size > 0:
                    return candidate
        return None

    def _persist_key_cache(self, artist: str, album: str, source_image: Path) -> None:
        plain_stem, hash_stem = self._cache_key_stems(artist, album)
        for stem in (plain_stem, hash_stem):
            target = self.cache_dir / f"{stem}.jpg"
            if target.exists() and target.stat().st_size > 0:
                continue
            try:
                target.write_bytes(source_image.read_bytes())
            except Exception:
                self.logger.debug("Failed to write key-cache image %s", target, exc_info=True)

    def _cache_and_signal(self, key: tuple[str, str], value: ArtworkResolution | None) -> ArtworkResolution | None:
        with self._cache_lock:
            self._resolved[key] = value
            inflight_event = self._inflight.pop(key, None)
            if inflight_event is not None:
                inflight_event.set()
        return value

    def resolve_cached_only(self, artist: str, album: str) -> ArtworkResolution | None:
        normalized_artist = artist.strip()
        normalized_album = album.strip()
        if not normalized_artist or not normalized_album:
            return None

        key = (normalized_artist.casefold(), normalized_album.casefold())
        with self._cache_lock:
            if key in self._resolved:
                return self._resolved[key]

        precached = self._find_precached_image(normalized_artist, normalized_album)
        if precached is None:
            return None

        result = ArtworkResolution(mbid="precache", image_path=precached)
        with self._cache_lock:
            self._resolved[key] = result
        return result

    def resolve(self, artist: str, album: str) -> ArtworkResolution | None:
        normalized_artist = artist.strip()
        normalized_album = album.strip()
        if not normalized_artist or not normalized_album:
            return None

        key = (normalized_artist.casefold(), normalized_album.casefold())
        with self._cache_lock:
            if key in self._resolved:
                return self._resolved[key]

            inflight_event = self._inflight.get(key)
            if inflight_event is None:
                inflight_event = threading.Event()
                self._inflight[key] = inflight_event
                is_owner = True
            else:
                is_owner = False

        if not is_owner:
            inflight_event.wait(timeout=self.timeout * 2)
            with self._cache_lock:
                return self._resolved.get(key)

        result: ArtworkResolution | None = None
        try:
            precached = self._find_precached_image(normalized_artist, normalized_album)
            if precached is not None:
                result = ArtworkResolution(mbid="precache", image_path=precached)
                return self._cache_and_signal(key, result)

            mbid = self._lookup_release_mbid(normalized_artist, normalized_album)
            if not mbid:
                return self._cache_and_signal(key, None)

            mbid_cached = self._find_mbid_cached_image(mbid)
            if self.use_cache and mbid_cached is not None:
                self._persist_key_cache(normalized_artist, normalized_album, mbid_cached)
                result = ArtworkResolution(mbid=mbid, image_path=mbid_cached)
                return self._cache_and_signal(key, result)

            image_bytes = self._fetch_cover_art(mbid)
            if not image_bytes:
                return self._cache_and_signal(key, None)

            cached_image = self.cache_dir / f"{mbid}.jpg"
            cached_image.write_bytes(image_bytes)
            self._persist_key_cache(normalized_artist, normalized_album, cached_image)
            result = ArtworkResolution(mbid=mbid, image_path=cached_image)
            return self._cache_and_signal(key, result)
        except Exception:
            self.logger.exception("Artwork resolution failed for artist=%s album=%s", normalized_artist, normalized_album)
            return self._cache_and_signal(key, None)

    def _lookup_release_mbid(self, artist: str, album: str) -> str | None:
        queries = [
            f"artist:{artist} AND release:{album}",
            f"release:{album}",
        ]

        for query in queries:
            response = self._throttled_get(
                MUSICBRAINZ_SEARCH_URL,
                params={
                    "query": query,
                    "fmt": "json",
                    "limit": 5,
                },
            )
            response.raise_for_status()

            payload = response.json()
            releases = payload.get("releases")
            if not isinstance(releases, list) or not releases:
                continue

            best = self._pick_best_release(releases, artist, album)
            if best:
                return best

        return None

    def _pick_best_release(self, releases: list[dict], artist: str, album: str) -> str | None:
        norm_artist = artist.casefold().strip()
        norm_album = album.casefold().strip()

        def _score(release: dict) -> tuple[int, int]:
            title = str(release.get("title") or "").casefold().strip()
            score = 0
            if title == norm_album:
                score += 4
            elif norm_album and (norm_album in title or title in norm_album):
                score += 2

            credits = release.get("artist-credit")
            if isinstance(credits, list):
                credit_text = " ".join(str(entry.get("name") or "") for entry in credits if isinstance(entry, dict))
                if norm_artist and norm_artist in credit_text.casefold():
                    score += 2

            api_score = int(release.get("score") or 0)
            return (score, api_score)

        best_release = max(releases, key=_score)
        mbid = str(best_release.get("id") or "").strip()
        return mbid or None

    def _fetch_cover_art(self, mbid: str) -> bytes | None:
        response = self._throttled_get(
            COVER_ART_ARCHIVE_URL.format(mbid=mbid),
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.content or None

    def _throttled_get(self, url: str, **kwargs: object) -> requests.Response:
        with self._request_lock:
            now = time.monotonic()
            wait_for = self._next_request_time - now
            if wait_for > 0:
                time.sleep(wait_for)

            response = self.session.get(url, timeout=self.timeout, **kwargs)
            self._next_request_time = time.monotonic() + self.min_request_interval
            return response
