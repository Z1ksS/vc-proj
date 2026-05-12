from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

_TERMS_PATH = Path(__file__).parent.parent.parent / "data" / "tech_terms.json"

# Negative lookbehind/lookahead: not preceded or followed by alphanumeric, underscore, or hyphen.
# Using custom boundaries instead of \b because \b breaks on special chars like C++, .NET, C#.
_WB_BEFORE = r"(?<![a-zA-Z0-9_\-])"
_WB_AFTER = r"(?![a-zA-Z0-9_\-])"


@lru_cache(maxsize=1)
def _load_patterns() -> tuple[tuple[str, re.Pattern[str]], ...]:
    data = json.loads(_TERMS_PATH.read_text(encoding="utf-8"))
    patterns: list[tuple[str, re.Pattern[str]]] = []
    for entry in data["terms"]:
        canonical: str = entry["canonical"]
        aliases: list[str] = entry.get("aliases", [canonical])
        # Longer aliases first so more specific patterns win in alternation
        aliases_sorted = sorted(aliases, key=len, reverse=True)
        escaped = [re.escape(a) for a in aliases_sorted]
        pattern = re.compile(
            _WB_BEFORE + "(?:" + "|".join(escaped) + ")" + _WB_AFTER,
            re.IGNORECASE,
        )
        patterns.append((canonical, pattern))
    return tuple(patterns)


def extract_technologies(text: str) -> list[str]:
    """Return sorted list of canonical tech names found in text."""
    if not text:
        return []
    return sorted(
        canonical
        for canonical, pattern in _load_patterns()
        if pattern.search(text)
    )


def reload_patterns() -> None:
    """Clear the pattern cache (call after updating tech_terms.json at runtime)."""
    _load_patterns.cache_clear()
