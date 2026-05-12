from __future__ import annotations

import re

# Matches "3000", "3 000", "3,000", "10 000"
_NUM = r'\d{1,3}(?:[\s,]\d{3})+|\d{3,6}'

_RANGE_RE = re.compile(rf'({_NUM})\s*[-–—]\s*({_NUM})')
_FROM_TO_RE = re.compile(rf'(?:від|from)\s+({_NUM})\s+(?:до|to)\s+({_NUM})', re.I)
_FROM_RE = re.compile(rf'(?:від|from)\s+({_NUM})', re.I)
_TO_RE = re.compile(rf'(?:до|to|up\s*to)\s+({_NUM})', re.I)

_CURRENCY_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r'\$|USD', re.I), 'USD'),
    (re.compile(r'€|EUR(?!\w)', re.I), 'EUR'),
    (re.compile(r'грн|UAH|₴', re.I), 'UAH'),
    (re.compile(r'PLN|zł', re.I), 'PLN'),
    (re.compile(r'£|GBP', re.I), 'GBP'),
]


def _clean_num(s: str) -> int | None:
    try:
        v = int(re.sub(r'[\s,]', '', s))
        return v if v >= 100 else None
    except ValueError:
        return None


def _detect_currency(text: str) -> str | None:
    for pattern, code in _CURRENCY_PATTERNS:
        if pattern.search(text):
            return code
    return None


def parse_salary(raw: str) -> tuple[int | None, int | None, str | None]:
    """Parse raw salary string → (min, max, currency). Returns (None, None, None) if unparseable."""
    if not raw or not raw.strip():
        return None, None, None

    currency = _detect_currency(raw)

    m = _FROM_TO_RE.search(raw)
    if m:
        lo, hi = _clean_num(m.group(1)), _clean_num(m.group(2))
        if lo and hi:
            return (lo, hi, currency)

    m = _RANGE_RE.search(raw)
    if m:
        lo, hi = _clean_num(m.group(1)), _clean_num(m.group(2))
        if lo and hi and lo < hi:
            return (lo, hi, currency)

    m = _FROM_RE.search(raw)
    if m:
        v = _clean_num(m.group(1))
        if v:
            return (v, None, currency)

    m = _TO_RE.search(raw)
    if m:
        v = _clean_num(m.group(1))
        if v:
            return (None, v, currency)

    nums = [_clean_num(n) for n in re.findall(_NUM, raw)]
    nums = [n for n in nums if n]
    if len(nums) >= 2:
        return (min(nums[:2]), max(nums[:2]), currency)
    if len(nums) == 1:
        return (nums[0], None, currency)

    return (None, None, currency)
