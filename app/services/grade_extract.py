from __future__ import annotations

import re

# Order matters: more specific grades checked first
_GRADE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r'\bprincipal\b', re.I), 'Principal'),
    (re.compile(r'\bstaff\b', re.I), 'Staff'),
    (re.compile(r'\b(?:tech\s+)?lead\b', re.I), 'Lead'),
    (re.compile(r'\bsenior\b|\bsr\.?\b', re.I), 'Senior'),
    (re.compile(r'\bmiddle\b|\bmid[\s\-]?level\b', re.I), 'Middle'),
    (re.compile(r'\bjunior\b|\bjr\.?\b', re.I), 'Junior'),
    (re.compile(r'\bintern\b|\btrainee\b|\bстажер\b', re.I), 'Intern'),
]


def extract_grade(title: str) -> str | None:
    """Return grade from job title, or None if not found."""
    if not title:
        return None
    for pattern, grade in _GRADE_PATTERNS:
        if pattern.search(title):
            return grade
    return None
