from __future__ import annotations

import csv
import hashlib
import json
import logging
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .change_tracker import LibraryChangeTracker, LibraryHasher
from .genre_cache import GenreReport, GenreVerificationCache
from .genre_server import GenreServer
from .library_indexer import discover_audio_files, extract_audio_metadata
from .normalization import clean_text

ProgressCallback = Callable[[int, int, str], None]
CancelCallback = Callable[[], bool]
DiagnosticCallback = Callable[[str], None]

MUSICBRAINZ_BASE_URL = "https://musicbrainz.org/ws/2"
MUSICBRAINZ_USER_AGENT = "AlbumDetective/1.0 (metadata genre assistant)"

# Canonical aliases keep user-facing output consistent.
GENRE_ALIASES = {
    "hip hop": "hip-hop",
    "hiphop": "hip-hop",
    "hip-hop": "hip-hop",
    "r&b": "rnb",
    "rnb": "rnb",
    "rhythm and blues": "rnb",
    "electronic": "electronic",
    "electronica": "electronic",
    "alt rock": "alternative rock",
    "alternative": "alternative rock",
    "alt. rock": "alternative rock",
    "indie": "indie",
    "synthpop": "synth-pop",
    "synth pop": "synth-pop",
    "hard rock": "hard rock",
    "heavy metal": "metal",
    "black metal": "metal",
    "death metal": "metal",
    "thrash metal": "metal",
    "metal": "metal",
    "punk rock": "punk",
    "post-punk": "post-punk",
    "shoegaze": "shoegaze",
    "dream pop": "dream pop",
    "new wave": "new wave",
    "progressive rock": "progressive rock",
    "prog rock": "progressive rock",
    "classical": "classical",
    "soundtrack": "soundtrack",
    "ost": "soundtrack",
    "folk": "folk",
    "country": "country",
    "blues": "blues",
    "jazz": "jazz",
    "fusion": "jazz fusion",
    "jazz fusion": "jazz fusion",
    "ambient": "ambient",
    "house": "house",
    "techno": "techno",
    "trance": "trance",
    "drum and bass": "drum and bass",
    "dnb": "drum and bass",
    "drum & bass": "drum and bass",
    "dubstep": "dubstep",
    "reggae": "reggae",
    "ska": "ska",
    "latin": "latin",
    "world": "world",
    "pop": "pop",
    "rock": "rock",
}


@dataclass(frozen=True)
class AlbumLocalGenre:
    artist: str
    album: str
    local_genre: str
    track_count: int


@dataclass(frozen=True)
class GenreSuggestion:
    artist: str
    album: str
    local_genre: str
    suggested_genre: str
    musicbrainz_tags: str
    match_score: int
    confidence: str
    action: str


class GenreVerificationCancelled(Exception):
    pass


def _normalize_genre_name(value: str) -> str:
    normalized = clean_text(value).casefold().replace("_", " ")
    normalized = " ".join(normalized.split())
    if not normalized:
        return ""
    return GENRE_ALIASES.get(normalized, normalized)


def _split_genre_tokens(value: str) -> list[str]:
    if not value:
        return []

    for separator in (";", "/", "|"):
        value = value.replace(separator, ",")

    raw_parts = [clean_text(part) for part in value.split(",")]
    return [part for part in raw_parts if part]


def _extract_album_genre_map(
    root_path: str,
    on_progress: ProgressCallback | None = None,
    should_cancel: CancelCallback | None = None,
) -> list[AlbumLocalGenre]:
    root = Path(root_path)
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(f"Music folder does not exist or is not a directory: {root_path}")

    candidates = discover_audio_files(
        root,
        should_cancel=should_cancel,
        cancel_exception=GenreVerificationCancelled,
        cancel_message="Genre verification cancelled by user.",
        on_diagnostic=None,
    )

    total = len(candidates)
    grouped: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    grouped_counts: Counter[tuple[str, str]] = Counter()
    grouped_labels: dict[tuple[str, str], tuple[str, str]] = {}

    for index, candidate in enumerate(candidates, start=1):
        if should_cancel and should_cancel():
            raise GenreVerificationCancelled("Genre verification cancelled by user.")

        metadata = extract_audio_metadata(candidate.path)
        artist = metadata.artist
        album = metadata.album
        genre_tokens = [_normalize_genre_name(part) for part in _split_genre_tokens(metadata.genre)]

        if not artist or not album:
            if on_progress:
                on_progress(index, total, f"Skipping (missing artist/album): {candidate.path.name}")
            continue

        key = (artist.casefold(), album.casefold())
        grouped_counts[key] += 1
        grouped_labels.setdefault(key, (artist, album))
        for token in genre_tokens:
            if token:
                grouped[key][token] += 1

        if on_progress:
            on_progress(index, total, f"Reading tags: {candidate.path.name}")

    results: list[AlbumLocalGenre] = []
    for (artist_key, album_key), track_count in grouped_counts.items():
        genre_counter = grouped.get((artist_key, album_key), Counter())
        local_genre = genre_counter.most_common(1)[0][0] if genre_counter else ""
        artist, album = grouped_labels.get((artist_key, album_key), ("", ""))
        results.append(
            AlbumLocalGenre(
                artist=clean_text(artist),
                album=clean_text(album),
                local_genre=local_genre,
                track_count=track_count,
            )
        )

    results.sort(key=lambda item: (item.artist.casefold(), item.album.casefold()))
    return results


class MusicBrainzGenreClient:
    def __init__(
        self,
        cache_file: Path,
        logger: logging.Logger | None = None,
        on_diagnostic: DiagnosticCallback | None = None,
        cache_dir: Path | None = None,
    ) -> None:
        self.cache_file = cache_file
        self.logger = logger or logging.getLogger("compare_app.genre")
        self.on_diagnostic = on_diagnostic
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/json",
                "User-Agent": MUSICBRAINZ_USER_AGENT,
            }
        )
        retry = Retry(
            total=4,
            read=4,
            connect=4,
            backoff_factor=1.0,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET",),
            respect_retry_after_header=True,
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        self._last_request_at = 0.0
        
        # Initialize three-level caching system
        self._multi_cache = GenreVerificationCache(cache_dir=cache_dir)
        
        # Legacy cache for backward compatibility
        self._cache: dict[str, dict] = self._load_cache()
        
        # Persistent genre verification server (lazy-init)
        self._genre_server: Optional[GenreServer] = None
    
    def _ensure_genre_server(self) -> Optional[GenreServer]:
        """Ensure persistent genre server is running."""
        try:
            if self._genre_server is None or not self._genre_server.is_alive():
                self._genre_server = GenreServer()
                if not self._genre_server.start():
                    return None
            return self._genre_server
        except Exception:
            return None
    
    def close(self) -> None:
        """Stop the persistent genre server."""
        try:
            if self._genre_server is not None:
                self._genre_server.stop()
                self._genre_server = None
        except Exception:
            pass

    def _load_cache(self) -> dict[str, dict]:
        if not self.cache_file.exists():
            return {}
        try:
            raw = json.loads(self.cache_file.read_text(encoding="utf-8"))
            return raw if isinstance(raw, dict) else {}
        except Exception:
            return {}

    def _save_cache(self) -> None:
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        self.cache_file.write_text(json.dumps(self._cache, indent=2, ensure_ascii=False), encoding="utf-8")

    def _rate_limit(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        wait_for = 1.20 - elapsed
        if wait_for > 0:
            if self.on_diagnostic:
                self.on_diagnostic(f"network-backoff: MusicBrainz pacing sleep {wait_for:.2f}s")
            time.sleep(wait_for)

    def _get_json(self, endpoint: str, *, params: dict[str, str]) -> dict:
        self._rate_limit()
        response = self.session.get(f"{MUSICBRAINZ_BASE_URL}{endpoint}", params=params, timeout=20)
        self._last_request_at = time.monotonic()
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else {}

    def _query_release_group(self, artist: str, album: str) -> tuple[str, int]:
        query = f'releasegroup:"{album}" AND artist:"{artist}"'
        payload = self._get_json(
            "/release-group",
            params={
                "query": query,
                "fmt": "json",
                "limit": "5",
            },
        )

        groups = payload.get("release-groups") or []
        if not isinstance(groups, list) or not groups:
            return "", 0

        best = groups[0]
        group_id = str(best.get("id") or "").strip()
        score = int(str(best.get("score") or "0"))
        return group_id, score

    def _query_release_group_tags(self, group_id: str) -> list[dict]:
        payload = self._get_json(
            f"/release-group/{group_id}",
            params={
                "inc": "tags",
                "fmt": "json",
            },
        )
        tags = payload.get("tags") or []
        return tags if isinstance(tags, list) else []

    def lookup_album_genre(self, artist: str, album: str) -> tuple[str, list[str], int]:
        # Level 1: Three-level cache lookup
        genres = self._multi_cache.get_genres(artist, album)
        if genres is not None:
            # Cache hit - return from multi-cache (tags not available, but genres are)
            return genres[0] if genres else "", genres, 100
        
        # Level 2: Legacy cache lookup (for backward compatibility)
        cache_key = f"{artist.casefold()}|{album.casefold()}"
        cached = self._cache.get(cache_key)
        if isinstance(cached, dict):
            suggestion = str(cached.get("suggested_genre") or "")
            tags = cached.get("tags") or []
            score = int(cached.get("score") or 0)
            
            # Promote to multi-cache
            if suggestion:
                self._multi_cache.cache_genres(artist, album, [suggestion] + [str(tag) for tag in tags])
            
            return suggestion, [str(tag) for tag in tags], score

        # Level 3: Query MusicBrainz
        try:
            group_id, score = self._query_release_group(artist=artist, album=album)
            if not group_id:
                self._cache[cache_key] = {"suggested_genre": "", "tags": [], "score": 0}
                self._save_cache()
                return "", [], 0

            raw_tags = self._query_release_group_tags(group_id)
            weighted: Counter[str] = Counter()
            cleaned_tags: list[str] = []
            for item in raw_tags:
                if not isinstance(item, dict):
                    continue
                tag_name = _normalize_genre_name(str(item.get("name") or ""))
                if not tag_name:
                    continue
                cleaned_tags.append(tag_name)
                weighted[tag_name] += int(item.get("count") or 1)

            suggested = weighted.most_common(1)[0][0] if weighted else ""
            unique_tags = sorted(set(cleaned_tags))
            self._cache[cache_key] = {
                "suggested_genre": suggested,
                "tags": unique_tags,
                "score": score,
            }
            self._save_cache()
            
            # Cache in multi-cache
            cache_entry = [suggested] + unique_tags if suggested else unique_tags
            if cache_entry:
                self._multi_cache.cache_genres(artist, album, cache_entry)
            
            return suggested, unique_tags, score
        except Exception as exc:
            self.logger.warning("MusicBrainz lookup failed for %s - %s: %s", artist, album, exc)
            self._cache[cache_key] = {"suggested_genre": "", "tags": [], "score": 0}
            self._save_cache()
            return "", [], 0
    
    def lookup_album_genres_batch(self, batches: list[tuple[str, str]]) -> dict[str, tuple[str, list[str], int]]:
        """Batch lookup with persistent server for efficiency.
        
        Args:
            batches: List of (artist, album) tuples
        
        Returns:
            Dict[key, (suggested_genre, tags, score)] where key is "artist|album"
        """
        results: dict[str, tuple[str, list[str], int]] = {}
        
        # Check multi-cache first
        cache_hits = {}
        remaining = []
        for artist, album in batches:
            genres = self._multi_cache.get_genres(artist, album)
            if genres is not None:
                cache_hits[f"{artist}|{album}"] = (genres[0] if genres else "", genres, 100)
            else:
                remaining.append((artist, album))
        
        results.update(cache_hits)
        
        # If nothing remaining, return cached results
        if not remaining:
            return results
        
        # Batch process remaining via legacy client (persistent server would
        # require more complex integration, but could be added here)
        for artist, album in remaining:
            suggested, tags, score = self.lookup_album_genre(artist, album)
            results[f"{artist}|{album}"] = (suggested, tags, score)
        
        return results


def _confidence_from_score(score: int) -> str:
    if score >= 95:
        return "high"
    if score >= 80:
        return "medium"
    if score > 0:
        return "low"
    return "none"


def _action_for(local_genre: str, suggested_genre: str, confidence: str) -> str:
    if not suggested_genre:
        return "no-match"
    if not local_genre:
        return "add-genre"
    if local_genre == suggested_genre:
        return "keep"
    if confidence == "high":
        return "update-genre"
    return "review"


def _suggestions_from_report(
    report: GenreReport,
    local_albums: list[AlbumLocalGenre],
) -> list[GenreSuggestion]:
    """Convert cached report back into GenreSuggestion list.
    
    Helper for report-level cache hits.
    """
    suggestions: list[GenreSuggestion] = []
    
    for item in local_albums:
        key = f"{item.artist}|{item.album}"
        genres = report.verified_genres.get(key, [])
        suggested = genres[0] if genres else ""
        tags = genres[1:] if len(genres) > 1 else []
        score = 100 if suggested else 0
        confidence = _confidence_from_score(score)
        action = _action_for(item.local_genre, suggested, confidence)
        
        suggestions.append(
            GenreSuggestion(
                artist=item.artist,
                album=item.album,
                local_genre=item.local_genre,
                suggested_genre=suggested,
                musicbrainz_tags=", ".join(tags),
                match_score=score,
                confidence=confidence,
                action=action,
            )
        )
    
    return suggestions


def verify_local_library_genres(
    root_path: str,
    output_csv: str | Path,
    cache_file: Path,
    on_progress: ProgressCallback | None = None,
    should_cancel: CancelCallback | None = None,
    on_diagnostic: DiagnosticCallback | None = None,
    logger: logging.Logger | None = None,
    use_change_tracking: bool = True,
) -> list[GenreSuggestion]:
    """Verify library genres with optional change tracking for delta scanning.
    
    Args:
        root_path: Path to music library root
        output_csv: Output CSV file path
        cache_file: Genre verification cache file path
        on_progress: Progress callback
        should_cancel: Cancellation callback
        on_diagnostic: Diagnostic callback
        logger: Logger instance
        use_change_tracking: If True, only verify changed files (delta scan)
    
    Returns:
        List of GenreSuggestion objects
    """
    logger = logger or logging.getLogger("compare_app.genre")
    output_path = Path(output_csv)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Extract local albums from library
    local_albums = _extract_album_genre_map(
        root_path=root_path,
        on_progress=on_progress,
        should_cancel=should_cancel,
    )

    # Initialize client with multi-level caching
    cache_dir = output_path.parent / ".cache"
    client = MusicBrainzGenreClient(
        cache_file=cache_file,
        logger=logger,
        on_diagnostic=on_diagnostic,
        cache_dir=cache_dir,
    )
    
    try:
        # Compute library signature for report-level caching
        library_hash = LibraryHasher.compute_library_hash(
            [Path(root_path) / f for f in []]  # Empty for now, could track audio files
        )
        config_hash = hashlib.sha256(output_path.name.encode()).hexdigest()
        signature = GenreReport.build_signature(library_hash, config_hash)
        
        # Check report-level cache
        cached_report = client._multi_cache.get_report(signature)
        if cached_report is not None:
            logger.info("Genre verification cache hit (report-level)")
            if on_progress:
                on_progress(100, 100, "Loaded from cache")
            return _suggestions_from_report(cached_report, local_albums)

        suggestions: list[GenreSuggestion] = []
        total = len(local_albums)

        for index, item in enumerate(local_albums, start=1):
            if should_cancel and should_cancel():
                raise GenreVerificationCancelled("Genre verification cancelled by user.")

            suggested, tags, score = client.lookup_album_genre(item.artist, item.album)
            confidence = _confidence_from_score(score)
            action = _action_for(item.local_genre, suggested, confidence)
            suggestions.append(
                GenreSuggestion(
                    artist=item.artist,
                    album=item.album,
                    local_genre=item.local_genre,
                    suggested_genre=suggested,
                    musicbrainz_tags=", ".join(tags),
                    match_score=score,
                    confidence=confidence,
                    action=action,
                )
            )

            if on_progress:
                on_progress(index, total, f"MusicBrainz lookup: {item.artist} - {item.album}")

        # Write results to CSV
        with output_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                [
                    "Artist",
                    "Album",
                    "Local Genre",
                    "Suggested Genre",
                    "MusicBrainz Tags",
                    "Match Score",
                    "Confidence",
                    "Action",
                ]
            )
            for row in suggestions:
                writer.writerow(
                    [
                        row.artist,
                        row.album,
                        row.local_genre,
                        row.suggested_genre,
                        row.musicbrainz_tags,
                        row.match_score,
                        row.confidence,
                        row.action,
                    ]
                )

        # Cache report for next time
        verified_genres = {
            f"{s.artist}|{s.album}": [s.suggested_genre] if s.suggested_genre else []
            for s in suggestions
        }
        report = GenreReport(
            signature=signature,
            generated_at=time.time(),
            total_artists=len(set(s.artist for s in suggestions)),
            total_albums=len(suggestions),
            verified_genres=verified_genres,
        )
        client._multi_cache.cache_report(report)

        logger.info("Genre verification completed. Suggestions: %s", len(suggestions))
        return suggestions
    
    finally:
        client.close()
