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

# ---------------------------------------------------------------------------
# Section-based extraction helpers
# ---------------------------------------------------------------------------

# Matches lines that look like section headers:
#   • must end with ":" (colon at end of line), OR
#   • are a known bare keyword (no colon required, e.g. "Requirements", "Benefits")
# Does NOT match bullet lines (-, –, •, *, digits).
_HEADER_RE = re.compile(
    r"""
    ^
    (?![ \t]*[-–•*·\d])          # not a bullet / numbered list item
    [ \t]*
    (?:
        ([^\n\r]{3,80}?)          # group 1 — header text ending with colon
        [ \t]*:[ \t]*
    |
        (                         # group 2 — bare known keywords (no colon)
            requirements?
            | qualifications?
            | must\s+have
            | nice\s+to\s+have
            | responsibilities?
            | benefits?(?:\s+we\s+offer)?
            | what\s+we\s+offer
            | experience
            | job\s+responsibilities?
            | what\s+we(?:'re|\s+are)?\s+looking\s+for
            | what\s+we\s+need
            | what\s+you(?:'ll)?\s+(?:need|bring|have)
            | your\s+(?:experience|skills?|background|requirements?|expertise)
            | our\s+requirements?
            | will\s+(?:definitely\s+)?be\s+a\s+plus
            | about\s+you
            # Ukrainian
            | вимоги
            | обов'язки
            | що\s+для\s+цього\s+потрібно
            | що\s+потрібно(?!\s+робити|\s+буде|\s+зробити)
            | що\s+для\s+нас\s+важливо
            | що\s+ми\s+очікуємо(?:\s+від\s+тебе)?
            | наші\s+очікування
            | кого\s+ми\s+шукаємо
            | основні\s+вимоги
            | технічні\s+вимоги
            | буде\s+перевагою
            | буде\s+плюсом
            | ми\s+пропонуємо
            | пропонуємо
            | для\s+нас\s+важливо
            | твої\s+скіли
            | що\s+важливо
            | would\s+be\s+a\s+plus
            | наш\s+ідеальний\s+кандидат
            | про\s+тебе
            | для\s+досягнення\s+результатів[^:\n]*знадобляться
        )
        [ \t]*
    )
    $
    """,
    re.MULTILINE | re.VERBOSE | re.IGNORECASE,
)

# Matches headers that introduce requirement-related sections.
# Uses search() (no ^ $ anchors) so compound headers like
# "Must Have Requirements" or "Key Technical Skills" match correctly.
_REQ_HEADER_RE = re.compile(
    r"""
    (?:
        requirements?
        | must[\s\-]?have
        | nice[\s\-]?to[\s\-]?have
        | required\s+(?:skills?|experience|qualifications?)
        | key\s+(?:skills?|requirements?)
        | technical\s+skills?
        | (?:your\s+)?experience(?:\s+and\s+skills?)?
        | skills?(?:\s+(?:and\s+)?(?:experience|requirements?))?
        | qualifications?
        | preferred(?:\s+qualifications?)?
        | what\s+we(?:'re|\s+are)?\s+looking\s+for
        | what\s+we\s+need
        | what\s+you(?:'ll)?\s+(?:need|bring|have)
        | will\s+(?:definitely\s+)?be\s+a\s+plus
        | your\s+expertise
        | about\s+you
        # Ukrainian
        | вимоги(?:\s+до\s+кандидат[аи])?
        | твій\s+досвід(?:\s+та\s+навички)?
        | досвід(?:\s+та\s+навички)?
        | навички
        | буде\s+(?:перевагою|плюсом)
        | ключові\s+вимоги
        | що\s+ми\s+шукаємо
        | що\s+для\s+цього\s+потрібно
        | що\s+потрібно(?!\s+робити|\s+буде|\s+зробити)
        | для\s+нас\s+важливо
        | що\s+для\s+нас\s+важливо
        | що\s+ми\s+очікуємо(?:\s+від\s+тебе)?
        | наші\s+очікування
        | кого\s+ми\s+шукаємо
        | основні\s+вимоги
        | технічні\s+вимоги
        | твої\s+скіли
        | що\s+важливо
        | would\s+be\s+a\s+plus
        | наш\s+ідеальний\s+кандидат
        | про\s+тебе
        | для\s+досягнення\s+результатів[^:\n]*знадобляться
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _normalize(text: str) -> str:
    """Replace smart quotes/apostrophes with ASCII equivalents."""
    return (
        text
        .replace("\u2018", "'").replace("\u2019", "'")
        .replace("\u02bc", "'").replace("`", "'")
        .replace("\u201c", '"').replace("\u201d", '"')
    )


def _split_sections(text: str) -> list[tuple[str, str]]:
    """Split job description into [(header, body)] pairs.

    The first element may have an empty header (preamble before the first header).
    """
    text = _normalize(text)
    matches = list(_HEADER_RE.finditer(text))
    if not matches:
        return [("", text)]

    sections: list[tuple[str, str]] = []

    pre = text[: matches[0].start()].strip()
    if pre:
        sections.append(("", pre))

    for i, m in enumerate(matches):
        header = (m.group(1) or m.group(2) or "").strip()
        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[body_start:body_end].strip()
        sections.append((header, body))

    return sections


def extract_requirements_section(text: str) -> str | None:
    """Return only the bodies of requirement-related sections.

    Returns None when no matching sections are found — caller should fall back
    to the full description text.
    """
    if not text:
        return None
    parts = [
        body
        for header, body in _split_sections(text)
        if body and _REQ_HEADER_RE.search(header)
    ]
    return "\n\n".join(parts) if parts else None


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
