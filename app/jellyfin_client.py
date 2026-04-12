from __future__ import annotations

from typing import Callable

import requests


ProgressCallback = Callable[[str], None]


class JellyfinClient:
    """Client for lightweight Jellyfin music ingestion using API key auth."""

    def __init__(self, server_url: str, api_key: str, timeout: int = 20) -> None:
        self.server_url = server_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "X-Emby-Token": api_key,
                "Accept": "application/json",
            }
        )

    def _get(self, path: str, params: dict | None = None) -> dict:
        response = self.session.get(
            f"{self.server_url}{path}",
            params=params or {},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def get_users(self) -> list[dict]:
        payload = self._get("/Users")
        if isinstance(payload, list):
            return payload
        return []

    def get_audio_items(self, user_id: str, on_progress: ProgressCallback | None = None) -> list[dict]:
        items: list[dict] = []
        start_index = 0
        limit = 200
        total = None

        while True:
            params = {
                "IncludeItemTypes": "Audio",
                "Recursive": "true",
                "Fields": "Path,Album,Artists,AlbumArtist,AlbumArtists",
                "SortBy": "SortName",
                "SortOrder": "Ascending",
                "StartIndex": start_index,
                "Limit": limit,
            }
            page = self._get(f"/Users/{user_id}/Items", params=params)
            page_items = page.get("Items", [])
            if total is None:
                total = page.get("TotalRecordCount", 0)

            if not page_items:
                break

            for item in page_items:
                artists = item.get("Artists") or item.get("AlbumArtists") or []
                artist = ""
                if artists:
                    artist = artists[0] or ""
                elif item.get("AlbumArtist"):
                    artist = str(item.get("AlbumArtist") or "")

                items.append(
                    {
                        "Track name": str(item.get("Name") or "").strip(),
                        "Artist": artist.strip(),
                        "Album": str(item.get("Album") or "").strip(),
                        "Path": str(item.get("Path") or "").strip() or None,
                    }
                )

            start_index += len(page_items)
            if on_progress:
                on_progress(f"Jellyfin audio fetched: {start_index}/{total or '?'}")

            if total is not None and start_index >= total:
                break

        return items
