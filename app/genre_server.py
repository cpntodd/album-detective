"""Persistent genre verification server using multiprocessing.

This module provides a long-lived background process that handles batched
genre verification requests against MusicBrainz, avoiding spawn/teardown
overhead and enabling efficient rate-limiting across batch submissions.

Architecture:
- Parent process submits batches of (artist, album) pairs via Pipe
- Child process handles requests with internal rate-limiting
- Results returned as dict[str, list[str]] where key is "artist|album"
"""

import json
import logging
import multiprocessing as mp
import multiprocessing.connection
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

# Rate limiting: 1 request per 1.2 seconds for MusicBrainz
MUSICBRAINZ_DELAY = 1.2


@dataclass
class GenreResult:
    """Result of a single genre verification query."""
    artist: str
    album: str
    genres: List[str]
    timestamp: float
    error: Optional[str] = None


def _create_session() -> requests.Session:
    """Create a requests session with retry strategy for MusicBrainz."""
    session = requests.Session()
    retry_strategy = Retry(
        total=3,
        backoff_factor=0.3,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update({"User-Agent": "album-detective/1.0"})
    return session


def _query_musicbrainz(session: requests.Session, artist: str, album: str) -> List[str]:
    """Query MusicBrainz for album and return genres.
    
    Returns empty list if not found or error occurs.
    """
    try:
        # Search for release by artist and album
        search_url = "https://musicbrainz.org/ws/2/release"
        params = {
            "artist": artist,
            "release": album,
            "fmt": "json",
            "limit": 1,
        }
        response = session.get(search_url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if not data.get("releases"):
            return []
        
        release = data["releases"][0]
        genres = release.get("genres", [])
        if not isinstance(genres, list):
            genres = []
        
        return [g.get("name", "") for g in genres if isinstance(g, dict)]
    except Exception as exc:
        logger.warning(f"MusicBrainz query failed for {artist} / {album}: {exc}")
        return []


def _server_loop(parent_conn: mp.connection.Connection) -> None:
    """Long-lived server loop processing genre verification batches.
    
    Receives lists of (artist, album) tuples from parent, returns
    dict[key, genres] where key is "artist|album".
    """
    session = _create_session()
    last_request_time = 0.0
    
    try:
        while True:
            try:
                # Wait for request from parent
                batch: List[tuple[str, str]] = parent_conn.recv()
                if batch is None:  # Sentinel to stop
                    break
                
                results: Dict[str, List[str]] = {}
                
                for artist, album in batch:
                    # Apply rate limiting
                    elapsed = time.time() - last_request_time
                    if elapsed < MUSICBRAINZ_DELAY:
                        time.sleep(MUSICBRAINZ_DELAY - elapsed)
                    
                    # Query MusicBrainz
                    genres = _query_musicbrainz(session, artist, album)
                    key = f"{artist}|{album}"
                    results[key] = genres
                    last_request_time = time.time()
                
                # Send results back
                parent_conn.send(results)
            except EOFError:
                break
            except Exception as exc:
                logger.error(f"Genre server error: {exc}")
                try:
                    parent_conn.send({"error": str(exc)})
                except Exception:
                    break
    finally:
        try:
            session.close()
        except Exception:
            pass


class GenreServer:
    """Persistent process for batched genre verification.
    
    Usage:
        server = GenreServer()
        server.start()
        results = server.submit([("Artist", "Album"), ...])
        server.stop()
    
    Each submit() call batches requests and returns dict[key, genres]
    where key is "artist|album".
    """
    
    def __init__(self) -> None:
        self._parent_conn: Optional[mp.connection.Connection] = None
        self._child_conn: Optional[mp.connection.Connection] = None
        self._proc: Optional[mp.Process] = None
    
    def start(self) -> bool:
        """Start the persistent genre server process.
        
        Returns True if successfully started, False otherwise.
        """
        try:
            self._parent_conn, self._child_conn = mp.Pipe()
            self._proc = mp.Process(
                target=_server_loop,
                args=(self._child_conn,),
                daemon=True,
            )
            self._proc.start()
            return True
        except Exception as exc:
            logger.error(f"Failed to start genre server: {exc}")
            return False
    
    def submit(self, batch: List[tuple[str, str]], timeout: float = 30.0) -> Dict[str, List[str]]:
        """Submit a batch of (artist, album) tuples for genre verification.
        
        Args:
            batch: List of (artist, album) tuples to verify
            timeout: Timeout in seconds for receiving results
        
        Returns:
            Dict[key, genres] where key is "artist|album", or empty dict on error
        """
        if not self._parent_conn or not self._proc or not self._proc.is_alive():
            return {}
        
        try:
            self._parent_conn.send(batch)
            if self._parent_conn.poll(timeout):
                result = self._parent_conn.recv()
                if isinstance(result, dict):
                    return result
        except Exception as exc:
            logger.error(f"Genre server submit error: {exc}")
        
        return {}
    
    def stop(self) -> None:
        """Stop the persistent genre server process."""
        try:
            if self._parent_conn:
                try:
                    self._parent_conn.send(None)  # Sentinel
                except Exception:
                    pass
                self._parent_conn.close()
            
            if self._proc and self._proc.is_alive():
                self._proc.terminate()
                self._proc.join(timeout=2.0)
                if self._proc.is_alive():
                    self._proc.kill()
                    self._proc.join()
        except Exception as exc:
            logger.error(f"Error stopping genre server: {exc}")
        finally:
            self._proc = None
            self._parent_conn = None
            self._child_conn = None
    
    def is_alive(self) -> bool:
        """Check if the genre server process is running."""
        return self._proc is not None and self._proc.is_alive()
    
    def __del__(self) -> None:
        """Ensure process is cleaned up on deletion."""
        try:
            self.stop()
        except Exception:
            pass
