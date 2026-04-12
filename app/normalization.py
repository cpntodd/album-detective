from __future__ import annotations

import re


_WHITESPACE_RE = re.compile(r"\s+")
_EDITION_HINT_RE = re.compile(
    r"\b("
    r"remaster(?:ed)?|"
    r"super\s+deluxe|deluxe|"
    r"special\s+edition|"
    r"collector(?:'s)?\s+edition|"
    r"expanded|"
    r"anniversary|"
    r"bonus\s+track(?:s)?|"
    r"edition|version"
    r")\b",
    re.IGNORECASE,
)
_TRAILING_BRACKET_RE = re.compile(r"\s*[\[(]([^\])]+)[\])]\s*$")
_TRAILING_SPLIT_RE = re.compile(r"\s*[-:–—]\s*([^:–—-]+)\s*$")


def clean_text(value: str | None) -> str:
    if value is None:
        return ""
    return _WHITESPACE_RE.sub(" ", str(value)).strip()


def norm_key(value: str | None) -> str:
    return clean_text(value).casefold()


def norm_album_key(value: str | None) -> str:
    album = clean_text(value)
    if not album:
        return ""

    # Strip trailing edition/remaster tags in brackets repeatedly.
    while True:
        bracket_match = _TRAILING_BRACKET_RE.search(album)
        if not bracket_match:
            break
        if not _EDITION_HINT_RE.search(bracket_match.group(1)):
            break
        album = clean_text(album[: bracket_match.start()])

    # Strip trailing split suffixes like " - 2008 Remaster" or ": Deluxe Edition".
    while True:
        split_match = _TRAILING_SPLIT_RE.search(album)
        if not split_match:
            break
        if not _EDITION_HINT_RE.search(split_match.group(1)):
            break
        album = clean_text(album[: split_match.start()])

    return norm_key(album)
