from __future__ import annotations

from pathlib import Path
from typing import Callable

import spotipy
from spotipy.oauth2 import SpotifyOAuth

from .models import TrackRecord
from .normalization import norm_key


ProgressCallback = Callable[[str], None]


class SpotifyClient:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        token_cache_path: Path,
    ) -> None:
        self.sp = spotipy.Spotify(
            auth_manager=SpotifyOAuth(
                client_id=client_id,
                client_secret=client_secret,
                redirect_uri=redirect_uri,
                scope="user-library-read user-follow-read",
                cache_path=str(token_cache_path),
                open_browser=True,
            )
        )

    def get_liked_tracks(self, on_progress: ProgressCallback | None = None) -> list[TrackRecord]:
        results: list[TrackRecord] = []
        offset = 0

        while True:
            page = self.sp.current_user_saved_tracks(limit=50, offset=offset)
            items = page.get("items", [])
            if not items:
                break

            for item in items:
                track = item.get("track") or {}
                artists = track.get("artists") or []
                artist_name = artists[0].get("name", "") if artists else ""
                album = (track.get("album") or {}).get("name", "")
                results.append(
                    TrackRecord(
                        track_name=track.get("name", "") or "",
                        artist=artist_name,
                        album=album,
                    )
                )

            offset += 50
            if on_progress:
                on_progress(f"Spotify liked tracks fetched: {len(results)}")

        return results

    def get_saved_albums(self, on_progress: ProgressCallback | None = None) -> list[TrackRecord]:
        results: list[TrackRecord] = []
        offset = 0

        while True:
            page = self.sp.current_user_saved_albums(limit=50, offset=offset)
            items = page.get("items", [])
            if not items:
                break

            for item in items:
                album = item.get("album") or {}
                artists = album.get("artists") or []
                artist_name = artists[0].get("name", "") if artists else ""
                results.append(
                    TrackRecord(
                        track_name="",
                        artist=artist_name,
                        album=album.get("name", "") or "",
                    )
                )

            offset += 50
            if on_progress:
                on_progress(f"Spotify saved albums fetched: {len(results)}")

        return results

    def get_followed_artists(self, on_progress: ProgressCallback | None = None) -> list[TrackRecord]:
        results: list[TrackRecord] = []
        after: str | None = None

        while True:
            page = self.sp.current_user_followed_artists(limit=50, after=after)
            artists_payload = page.get("artists", {})
            items = artists_payload.get("items", [])
            if not items:
                break

            for artist in items:
                results.append(
                    TrackRecord(
                        track_name="",
                        artist=artist.get("name", "") or "",
                        album="",
                    )
                )

            after = (artists_payload.get("cursors") or {}).get("after")
            if on_progress:
                on_progress(f"Spotify followed artists fetched: {len(results)}")
            if not after:
                break

        return results

    def get_normalized_library(self, on_progress: ProgressCallback | None = None) -> list[TrackRecord]:
        liked = self.get_liked_tracks(on_progress=on_progress)
        albums = self.get_saved_albums(on_progress=on_progress)
        artists = self.get_followed_artists(on_progress=on_progress)

        combined = liked + albums + artists

        seen: set[tuple[str, str, str]] = set()
        unique: list[TrackRecord] = []
        for rec in combined:
            key = (norm_key(rec.track_name), norm_key(rec.artist), norm_key(rec.album))
            if key in seen:
                continue
            seen.add(key)
            unique.append(rec)

        return unique
