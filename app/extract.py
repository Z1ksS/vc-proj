from __future__ import annotations

import argparse
import logging
import os
import sys
from collections import Counter

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import delete, select

_db_url = os.getenv("DATABASE_URL", "sqlite:///./jobs.db")
if _db_url.startswith("postgresql"):
    from sqlalchemy.dialects.postgresql import insert as _insert
else:
    from sqlalchemy.dialects.sqlite import insert as _insert

from app.db import SessionLocal
from app.models import JobRecord, Technology, VacancyTechnology
from app.services.tech_extract import (
    _REQ_HEADER_RE,
    _split_sections,
    extract_requirements_section,
    extract_technologies,
)

LOG_PATH = os.getenv("EXTRACT_LOG_PATH", "logs/extract.log")
LOGGER_NAME = "job_vc.extract"
COMMIT_EVERY = 100


def _get_logger() -> logging.Logger:
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


def _get_or_create_tech(db, name: str, cache: dict[str, int]) -> int:
    if name in cache:
        return cache[name]
    db.execute(_insert(Technology).values(name=name).on_conflict_do_nothing())
    tech_id = db.execute(select(Technology.id).where(Technology.name == name)).scalar_one()
    cache[name] = tech_id
    return tech_id


def run_extraction(reprocess: bool = False) -> dict[str, int]:
    logger = _get_logger()
    stats = {"processed": 0, "skipped": 0, "total_techs": 0, "zero_techs": 0}

    with SessionLocal() as db:
        query = (
            select(JobRecord.id, JobRecord.title, JobRecord.description)
            .where(JobRecord.description.isnot(None))
        )

        if not reprocess:
            already_processed = select(VacancyTechnology.vacancy_id).distinct()
            query = query.where(JobRecord.id.not_in(already_processed))

        rows = db.execute(query).fetchall()
        logger.info("Vacancies to process: %d | reprocess=%s", len(rows), reprocess)

        tech_cache: dict[str, int] = {
            row.name: row.id
            for row in db.execute(select(Technology.name, Technology.id)).fetchall()
        }

        for i, (job_id, title, description) in enumerate(rows):
            if reprocess:
                db.execute(
                    delete(VacancyTechnology).where(VacancyTechnology.vacancy_id == job_id)
                )

            req_text = extract_requirements_section(description or "")
            text = f"{title} {req_text if req_text is not None else (description or '')}"
            techs = extract_technologies(text)

            for tech_name in techs:
                tech_id = _get_or_create_tech(db, tech_name, tech_cache)
                db.execute(
                    _insert(VacancyTechnology)
                    .values(vacancy_id=job_id, tech_id=tech_id)
                    .on_conflict_do_nothing()
                )

            stats["processed"] += 1
            stats["total_techs"] += len(techs)
            if not techs:
                stats["zero_techs"] += 1

            if (i + 1) % COMMIT_EVERY == 0:
                db.commit()
                logger.info("Progress: %d/%d | techs_so_far=%d", i + 1, len(rows), stats["total_techs"])

        db.commit()

    logger.info(
        "Extraction finished | processed=%d zero_techs=%d total_techs=%d",
        stats["processed"], stats["zero_techs"], stats["total_techs"],
    )
    return stats


def run_stats() -> None:
    """Dry-run: report section detection coverage across all vacancies with descriptions."""
    with SessionLocal() as db:
        rows = db.execute(
            select(JobRecord.id, JobRecord.title, JobRecord.description, JobRecord.source)
            .where(JobRecord.description.isnot(None))
        ).fetchall()

    total = len(rows)
    if not total:
        print("No vacancies with descriptions found.")
        return

    section_found = 0
    header_counter: Counter[str] = Counter()
    source_total: Counter[str] = Counter()
    source_found: Counter[str] = Counter()
    techs_with_section: list[int] = []
    techs_fallback: list[int] = []

    for _id, title, description, source in rows:
        source_total[source] += 1
        desc = description or ""
        sections = _split_sections(desc)
        matched = [h for h, body in sections if body and _REQ_HEADER_RE.search(h)]

        if matched:
            section_found += 1
            source_found[source] += 1
            for h in matched:
                header_counter[h.lower().strip()] += 1
            req_text = "\n".join(
                body for h, body in sections if body and _REQ_HEADER_RE.search(h)
            )
            n = len(extract_technologies(f"{title} {req_text}"))
            techs_with_section.append(n)
        else:
            n = len(extract_technologies(f"{title} {desc}"))
            techs_fallback.append(n)

    fallback = total - section_found
    avg_s = sum(techs_with_section) / len(techs_with_section) if techs_with_section else 0.0
    avg_f = sum(techs_fallback) / len(techs_fallback) if techs_fallback else 0.0

    w = 62
    print("=" * w)
    print("  SECTION EXTRACTION COVERAGE REPORT")
    print("=" * w)
    print(f"  Total vacancies with description : {total}")
    print(f"  Section found                    : {section_found:5d}  ({section_found / total * 100:.1f}%)")
    print(f"  Fallback (full text)             : {fallback:5d}  ({fallback / total * 100:.1f}%)")
    print()
    print(f"  Avg techs — section found        : {avg_s:.1f}")
    print(f"  Avg techs — fallback             : {avg_f:.1f}")
    print()

    print("  Top matched headers (by frequency):")
    for header, count in header_counter.most_common(20):
        bar = "█" * min(count // max(total // 200, 1), 30)
        print(f"    {count:5d}  {header[:45]:<45}  {bar}")
    print()

    print("  Fallback rate by source:")
    for src in sorted(source_total):
        t = source_total[src]
        f = t - source_found[src]
        pct = f / t * 100 if t else 0.0
        print(f"    {src:<18}  {f:4d}/{t:<5d}  ({pct:.1f}% fallback)")
    print("=" * w)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Extract tech stack from vacancy descriptions using regex dictionary")
    p.add_argument(
        "--reprocess-all",
        action="store_true",
        default=False,
        help="Reprocess all vacancies, replacing existing tech entries (use after updating tech_terms.json)",
    )
    p.add_argument(
        "--stats",
        action="store_true",
        default=False,
        help="Dry-run: show section detection coverage stats without writing to DB",
    )
    return p


def main() -> None:
    args = build_parser().parse_args()
    if args.stats:
        run_stats()
        return
    stats = run_extraction(reprocess=args.reprocess_all)
    print("Extraction completed.")
    for key, value in stats.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
