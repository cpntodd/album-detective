from __future__ import annotations

import re


_WHITESPACE_RE = re.compile(r"\s+")


def clean_text(value: str | None) -> str:
    if value is None:
        return ""
    return _WHITESPACE_RE.sub(" ", str(value)).strip()


def norm_key(value: str | None) -> str:
    return clean_text(value).casefold()
