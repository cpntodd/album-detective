from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path

# Keep tests lightweight and independent from optional runtime deps.
if "mutagen" not in sys.modules:
    sys.modules["mutagen"] = types.SimpleNamespace(File=lambda *_args, **_kwargs: None)

from app.genre_verifier import MusicBrainzGenreClient, _action_for, _confidence_from_score


class GenreActionTests(unittest.TestCase):
    def test_confidence_buckets(self) -> None:
        self.assertEqual(_confidence_from_score(0), "none")
        self.assertEqual(_confidence_from_score(79), "low")
        self.assertEqual(_confidence_from_score(80), "medium")
        self.assertEqual(_confidence_from_score(95), "high")

    def test_action_no_match(self) -> None:
        self.assertEqual(_action_for(local_genre="rock", suggested_genre="", confidence="none"), "no-match")

    def test_action_add_genre(self) -> None:
        self.assertEqual(_action_for(local_genre="", suggested_genre="rock", confidence="high"), "add-genre")

    def test_action_keep(self) -> None:
        self.assertEqual(_action_for(local_genre="rock", suggested_genre="rock", confidence="high"), "keep")

    def test_action_update_genre_on_high_confidence(self) -> None:
        self.assertEqual(_action_for(local_genre="pop", suggested_genre="rock", confidence="high"), "update-genre")

    def test_action_review_when_not_high_confidence(self) -> None:
        self.assertEqual(_action_for(local_genre="pop", suggested_genre="rock", confidence="medium"), "review")


class GenreCacheTests(unittest.TestCase):
    def test_lookup_uses_cache_without_network_calls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_file = Path(tmp) / "genre_cache.json"
            cache_file.write_text(
                '{"artist a|album b":{"suggested_genre":"rock","tags":["rock","indie"],"score":99}}',
                encoding="utf-8",
            )

            client = MusicBrainzGenreClient(cache_file=cache_file)

            def _should_not_run(*_args, **_kwargs):  # type: ignore[no-untyped-def]
                raise AssertionError("Network path should not be executed for cache hit")

            client._query_release_group = _should_not_run  # type: ignore[method-assign]
            client._query_release_group_tags = _should_not_run  # type: ignore[method-assign]

            suggested, tags, score = client.lookup_album_genre("Artist A", "Album B")

            self.assertEqual(suggested, "rock")
            self.assertEqual(tags, ["rock", "indie"])
            self.assertEqual(score, 99)


if __name__ == "__main__":
    unittest.main()
