"""
Phase 4c — batch salary + grade extraction.

Reads the raw `salary` field and `title` from every vacancy,
writes structured salary_min / salary_max / salary_currency / grade back.

Usage:
    python -m app.enrich_meta               # process all records
    python -m app.enrich_meta --only-new    # only where grade IS NULL (after daily ingest)
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

from sqlalchemy import select, update

from app.db import SessionLocal
from app.models import JobRecord
from app.services.grade_extract import extract_grade
from app.services.salary_parse import parse_salary

LOG_PATH = os.getenv("META_LOG_PATH", "logs/enrich_meta.log")
LOGGER_NAME = "job_vc.enrich_meta"
COMMIT_EVERY = 200


def _get_logger() -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    log_dir = os.path.dirname(LOG_PATH)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
    fh = logging.FileHandler(LOG_PATH, encoding="utf-8")
    fh.setFormatter(formatter)
    logger.addHandler(fh)
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(formatter)
    logger.addHandler(ch)
    logger.propagate = False
    return logger


def run_enrich_meta(only_new: bool = False) -> dict[str, int]:
    logger = _get_logger()
    stats = {"processed": 0, "grade_set": 0, "salary_set": 0}

    with SessionLocal() as db:
        query = select(JobRecord.id, JobRecord.title, JobRecord.salary)
        if only_new:
            query = query.where(JobRecord.grade.is_(None))

        rows = db.execute(query).fetchall()
        logger.info("Records to process: %d | only_new=%s", len(rows), only_new)

        for i, (job_id, title, salary_raw) in enumerate(rows):
            grade = extract_grade(title or "")
            sal_min, sal_max, sal_cur = parse_salary(salary_raw or "")

            values: dict = {}
            if grade is not None:
                values["grade"] = grade
                stats["grade_set"] += 1
            if sal_min is not None or sal_max is not None:
                values["salary_min"] = sal_min
                values["salary_max"] = sal_max
                values["salary_currency"] = sal_cur
                stats["salary_set"] += 1

            if values:
                db.execute(update(JobRecord).where(JobRecord.id == job_id).values(**values))

            stats["processed"] += 1

            if (i + 1) % COMMIT_EVERY == 0:
                db.commit()
                logger.info("Progress: %d/%d", i + 1, len(rows))

        db.commit()

    logger.info(
        "Meta enrichment finished | processed=%d grade_set=%d salary_set=%d",
        stats["processed"], stats["grade_set"], stats["salary_set"],
    )
    return stats


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Extract grade and salary metadata from vacancy fields")
    p.add_argument(
        "--only-new",
        action="store_true",
        help="Process only vacancies where grade IS NULL (incremental, after daily ingest)",
    )
    return p


def main() -> None:
    args = build_parser().parse_args()
    stats = run_enrich_meta(only_new=args.only_new)
    print("Meta enrichment completed.")
    for key, value in stats.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
