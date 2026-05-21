from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from typing import Iterable

from sqlalchemy import and_, select, update
from sqlalchemy.orm import Session

from app.db import SessionLocal, engine
from app.models import Base, JobRecord
from app.services.dedupe import dedupe_jobs
from app.services.normalize import normalize_job
from app.services.tech_extract import extract_technologies
from parsers.djinni import DjinniParser
from parsers.dou import DouParser
from parsers.nofluffjobs import NoFluffJobsParser
from parsers.robotaua import RobotauaParser
from parsers.workua import WorkUaParser


_PARSER_REGISTRY = {
    "djinni": DjinniParser,
    "workua": WorkUaParser,
    "nofluffjobs": NoFluffJobsParser,
    "dou": DouParser,
    "robotaua": RobotauaParser,
}

ALL_SOURCES = tuple(_PARSER_REGISTRY.keys())

LOG_PATH = os.getenv("INGEST_LOG_PATH", "logs/ingest.log")
LOGGER_NAME = "job_vc.ingest"
CLOSE_AFTER_DAYS = int(os.getenv("CLOSE_AFTER_DAYS", "3"))

_DEFAULT_KEYWORDS_RAW = os.getenv("INGEST_KEYWORDS", "DevOps")
DEFAULT_KEYWORDS = [k.strip() for k in _DEFAULT_KEYWORDS_RAW.split(",") if k.strip()]

_MILTECH_RE = re.compile(
    r"\b(?:miltech|deftech|military|defence|defense|"
    r"drone(?:\s+(?:tech|soft|system|platform))?|"
    r"uav|uas|unmanned\s+aerial|"
    r"weapon\s+systems?|ballistic|munitions?|warfighter|"
    r"battlefield\s+(?:management|system)|"
    r"бпла|безпілот|оборонн|військов|зброй)\b",
    re.IGNORECASE,
)


def is_miltech(title: str, description: str | None = None) -> bool:
    # Title-only detection to avoid false positives from outsourcing companies
    # whose descriptions mention defense clients
    return bool(_MILTECH_RE.search(title))

# Keywords that require tech filtering — vacancies from these categories may be non-technical.
_OTHER_KEYWORDS: frozenset[str] = frozenset({"other"})

# Fallback title pattern for jobs without a description (e.g. DOU Other).
# Matches common technical role nouns so non-tech vacancies (HR, finance, etc.) are dropped.
_TECH_TITLE_RE = re.compile(
    r"\b(?:engineer|developer|programmer|architect|devops|sre|"
    r"tester|sysadmin|firmware|embedded|"
    r"(?:data|ai|ml|machine\s+learning)\s+scientist|"
    r"(?:data|business\s+intelligence|bi)\s+analyst|"
    r"(?:system|network|database|cloud|security)\s+admin(?:istrator)?)\b",
    re.IGNORECASE,
)


def _is_technical_other(job) -> bool:
    """Return True if a job from the 'Other' category appears to be technical."""
    text = " ".join(x for x in [job.title, job.description] if x)
    if extract_technologies(text):
        return True
    # Description-less jobs (e.g. DOU listing-only): fall back to title heuristic.
    return bool(_TECH_TITLE_RE.search(job.title or ""))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _get_ingest_logger() -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    log_dir = os.path.dirname(LOG_PATH)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
    file_handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    logger.propagate = False
    return logger


def _enabled_sources_from_env() -> set[str]:
    raw = os.getenv("ENABLE_SOURCES", ",".join(ALL_SOURCES))
    return {part.strip().lower() for part in raw.split(",") if part.strip()}


def get_parsers() -> dict[str, object]:
    enabled = _enabled_sources_from_env()
    return {
        name: cls()
        for name, cls in _PARSER_REGISTRY.items()
        if name in enabled
    }


def _upsert_jobs(db: Session, jobs: Iterable) -> tuple[int, int]:
    inserted = 0
    updated = 0
    now = _now()

    for job in jobs:
        existing = db.execute(
            select(JobRecord).where(JobRecord.source_job_id == job.source_job_id)
        ).scalar_one_or_none()

        miltech_flag = is_miltech(job.title, job.description)

        if existing:
            existing.title = job.title
            existing.company = job.company
            existing.salary = job.salary
            existing.link = job.link
            existing.job_format = job.job_format
            existing.normalized_title = job.normalized_title
            existing.normalized_company = job.normalized_company
            existing.dedupe_fingerprint = job.dedupe_fingerprint
            existing.description = job.description
            existing.last_seen_at = now
            existing.is_miltech = miltech_flag
            if existing.closed_at is not None:
                # Vacancy reappeared after being marked closed.
                existing.closed_at = None
            updated += 1
            continue

        db.add(JobRecord(
            source=job.source,
            source_job_id=job.source_job_id,
            title=job.title,
            company=job.company,
            salary=job.salary,
            link=job.link,
            job_format=job.job_format,
            normalized_title=job.normalized_title,
            normalized_company=job.normalized_company,
            dedupe_fingerprint=job.dedupe_fingerprint,
            description=job.description,
            first_seen_at=now,
            last_seen_at=now,
            canonical_vacancy_id=job.source_job_id,
            is_miltech=miltech_flag,
        ))
        inserted += 1

    db.commit()
    return inserted, updated


def _mark_closed(db: Session, sources_ingested: set[str], logger: logging.Logger) -> int:
    """
    Mark vacancies from ingested sources as closed if last_seen_at is older
    than CLOSE_AFTER_DAYS and they have not been marked closed already.
    Only runs against sources that were part of this run — we can't infer
    closure for sources we didn't scrape.
    """
    if not sources_ingested:
        return 0

    cutoff = _now() - timedelta(days=CLOSE_AFTER_DAYS)
    result = db.execute(
        update(JobRecord)
        .where(
            and_(
                JobRecord.source.in_(sources_ingested),
                JobRecord.last_seen_at < cutoff,
                JobRecord.closed_at.is_(None),
            )
        )
        .values(closed_at=_now())
    )
    db.commit()

    count = result.rowcount
    if count:
        logger.info(
            "Marked %d vacancies as closed (not seen in %d days) sources=%s",
            count,
            CLOSE_AFTER_DAYS,
            sorted(sources_ingested),
        )
    return count


_CATEGORIES_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "categories.json")


def load_keywords_by_source(path: str = _CATEGORIES_PATH) -> dict[str, list[str]]:
    """Load data/categories.json and return {source: [keywords]} with per-source keyword lists."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    result: dict[str, list[str]] = {}
    for cat in data["categories"]:
        for source, kws in cat["sources"].items():
            if kws:
                for kw in kws:
                    if kw not in result.setdefault(source, []):
                        result[source].append(kw)
    return result


def run_ingestion(
    keywords: list[str] | None = None,
    sources: list[str] | None = None,
    keywords_by_source: dict[str, list[str]] | None = None,
) -> dict[str, int]:
    logger = _get_ingest_logger()
    Base.metadata.create_all(bind=engine)

    selected_keywords = keywords or DEFAULT_KEYWORDS
    parser_map = get_parsers()
    selected_sources = (
        [s.lower() for s in sources] if sources else list(parser_map.keys())
    )

    logger.info(
        "Ingestion started | keywords=%s | sources=%s | enabled_sources=%s",
        selected_keywords,
        selected_sources,
        sorted(parser_map.keys()),
    )

    total_raw = 0
    normalized_jobs = []
    sources_ingested: set[str] = set()

    for source in selected_sources:
        parser = parser_map.get(source)
        if parser is None:
            logger.warning("Skipping unknown or disabled source '%s'", source)
            continue
        sources_ingested.add(source)
        source_keywords = (keywords_by_source or {}).get(source) or selected_keywords
        for keyword in source_keywords:
            try:
                jobs = parser.parse(keyword) or []
                logger.info(
                    "Parsed source='%s' keyword='%s' jobs=%d",
                    source, keyword, len(jobs),
                )
            except Exception:
                logger.exception("Parser failed source='%s' keyword='%s'", source, keyword)
                jobs = []
            if keyword.lower() in _OTHER_KEYWORDS and jobs:
                before = len(jobs)
                jobs = [j for j in jobs if _is_technical_other(j)]
                dropped = before - len(jobs)
                if dropped:
                    logger.info(
                        "Other-filter source='%s' kept=%d dropped=%d",
                        source, len(jobs), dropped,
                    )
            total_raw += len(jobs)
            normalized_jobs.extend(normalize_job(job, source=source) for job in jobs)

    deduped = dedupe_jobs(normalized_jobs)

    with SessionLocal() as db:
        inserted, updated = _upsert_jobs(db, deduped)
        closed = _mark_closed(db, sources_ingested, logger)

    stats = {
        "raw_jobs": total_raw,
        "normalized_jobs": len(normalized_jobs),
        "deduped_jobs": len(deduped),
        "inserted": inserted,
        "updated": updated,
        "closed": closed,
    }
    logger.info("Ingestion finished | stats=%s", stats)
    return stats


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ingest jobs from configured sources")
    parser.add_argument(
        "--keywords",
        nargs="+",
        default=DEFAULT_KEYWORDS,
        help="Keywords to search, e.g. --keywords DevOps Frontend",
    )
    parser.add_argument(
        "--sources",
        nargs="+",
        default=None,
        choices=list(ALL_SOURCES),
        help="Sources to ingest from. Defaults to all enabled sources.",
    )
    parser.add_argument(
        "--all-categories",
        action="store_true",
        default=False,
        help="Use data/categories.json for per-source keyword mapping (overrides --keywords).",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.all_categories:
        kw_by_source = load_keywords_by_source()
        stats = run_ingestion(keywords_by_source=kw_by_source, sources=args.sources)
    else:
        stats = run_ingestion(keywords=args.keywords, sources=args.sources)
    print("Ingestion completed.")
    for key, value in stats.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
