from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from models.job import Job


SPACES_RE = re.compile(r"\s+")
NON_WORD_RE = re.compile(r"[^\w\s]")

# Max length of the String(256) columns in app.models.JobRecord. Values longer
# than this make Postgres reject the whole batch insert (StringDataRightTruncation),
# so we cap them here — the single funnel before persistence.
_VARCHAR_LIMIT = 256


@dataclass(slots=True)
class NormalizedJob:
    source: str
    source_job_id: str
    title: str
    company: str
    salary: str
    link: str
    job_format: str
    normalized_title: str
    normalized_company: str
    dedupe_fingerprint: str
    description: str | None = field(default=None)


def normalize_text(value: str) -> str:
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = NON_WORD_RE.sub(" ", normalized)
    normalized = SPACES_RE.sub(" ", normalized).strip()
    return normalized


def normalize_salary(value: str) -> str:
    if not value:
        return ""
    cleaned = SPACES_RE.sub(" ", value).strip()
    cleaned = cleaned.replace(" ", " ")
    return cleaned


def build_fingerprint(title: str, company: str) -> str:
    return f"{title}::{company}"


def _cap(value: str, limit: int = _VARCHAR_LIMIT) -> str:
    return value[:limit]


def normalize_job(job: Job, source: str) -> NormalizedJob:
    title = _cap((job.title or "").strip())
    company = _cap((job.company or "").strip())
    salary = _cap(normalize_salary(job.salary or ""))
    link = (job.link or "").strip()
    job_format = _cap((job.job_format or "").strip())
    normalized_title = _cap(normalize_text(title))
    normalized_company = _cap(normalize_text(company))
    fingerprint = build_fingerprint(normalized_title, normalized_company)
    source_job_id = (job.id or "").strip() or f"{source}:{link or fingerprint}"
    return NormalizedJob(
        source=source,
        source_job_id=source_job_id,
        title=title,
        company=company,
        salary=salary,
        link=link,
        job_format=job_format,
        normalized_title=normalized_title,
        normalized_company=normalized_company,
        dedupe_fingerprint=fingerprint,
        description=job.description,
    )
