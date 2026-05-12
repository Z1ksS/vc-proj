from __future__ import annotations

from collections.abc import Iterable

from app.services.normalize import NormalizedJob

try:
    from rapidfuzz import fuzz
except Exception:  # pragma: no cover - optional dependency
    fuzz = None


def dedupe_jobs(jobs: Iterable[NormalizedJob], fuzzy_threshold: int = 95) -> list[NormalizedJob]:
    unique_by_fp: dict[str, NormalizedJob] = {}
    if fuzz is None:
        for job in jobs:
            unique_by_fp.setdefault(job.dedupe_fingerprint, job)
        return list(unique_by_fp.values())

    for job in jobs:
        if job.dedupe_fingerprint in unique_by_fp:
            continue
        matched = False
        for existing_fp in unique_by_fp:
            score = fuzz.ratio(job.dedupe_fingerprint, existing_fp)
            if score >= fuzzy_threshold:
                matched = True
                break
        if not matched:
            unique_by_fp[job.dedupe_fingerprint] = job
    return list(unique_by_fp.values())

