from __future__ import annotations

import argparse
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup
from sqlalchemy import select, update

from app.db import SessionLocal
from app.models import JobRecord

LOG_PATH = os.getenv("ENRICH_LOG_PATH", "logs/enrich.log")
LOGGER_NAME = "job_vc.enrich"
REQUEST_DELAY = float(os.getenv("ENRICH_DELAY", "1.5"))
BATCH_SIZE = int(os.getenv("ENRICH_BATCH_SIZE", "200"))

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "uk-UA,uk;q=0.9,en-US;q=0.8",
}

_SELECTORS: dict[str, str] = {
    "djinni": "div.job-post__description",
    "dou": "div.vacancy-section",
    "workua": "div#job-description",
    "nofluffjobs": "article",
}


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


def _extract_text(el) -> str:
    text = el.get_text(separator="\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = "\n".join(line.strip() for line in text.splitlines())
    return text.strip()


_GONE = object()  # sentinel: vacancy deleted/hidden


def _fetch_description(session: requests.Session, url: str, selector: str):
    try:
        resp = session.get(url, headers=_HEADERS, timeout=15)
    except requests.RequestException:
        return None
    if resp.status_code == 404:
        return _GONE
    try:
        resp.raise_for_status()
    except requests.RequestException:
        return None
    soup = BeautifulSoup(resp.text, "lxml")
    el = soup.select_one(selector)
    if not el:
        return _GONE
    text = _extract_text(el)
    return text if text else _GONE


def run_enrichment(sources: list[str] | None = None, limit: int | None = None) -> dict[str, int]:
    logger = _get_logger()
    session = requests.Session()

    target_sources = sources or list(_SELECTORS.keys())
    unknown = [s for s in target_sources if s not in _SELECTORS]
    if unknown:
        logger.warning("Unknown sources (no selector defined): %s", unknown)
        target_sources = [s for s in target_sources if s in _SELECTORS]

    stats: dict[str, int] = {s: 0 for s in target_sources}
    stats["errors"] = 0
    stats["closed"] = 0

    logger.info("Enrichment started | sources=%s | batch_size=%d", target_sources, BATCH_SIZE)

    with SessionLocal() as db:
        for source in target_sources:
            selector = _SELECTORS[source]
            query = (
                select(JobRecord.id, JobRecord.link)
                .where(JobRecord.source == source)
                .where(JobRecord.description.is_(None))
                .where(JobRecord.closed_at.is_(None))
            )
            if limit:
                query = query.limit(limit)
            rows = db.execute(query).fetchall()
            logger.info("source='%s' pending=%d", source, len(rows))

            for i, (job_id, link) in enumerate(rows):
                if i > 0:
                    time.sleep(REQUEST_DELAY)

                result = _fetch_description(session, link, selector)
                if result is _GONE:
                    db.execute(
                        update(JobRecord)
                        .where(JobRecord.id == job_id)
                        .values(closed_at=datetime.now(timezone.utc))
                    )
                    stats["closed"] += 1
                    continue
                if result is None:
                    stats["errors"] += 1
                    continue

                db.execute(
                    update(JobRecord)
                    .where(JobRecord.id == job_id)
                    .values(description=result)
                )
                stats[source] += 1

                if (i + 1) % 50 == 0:
                    db.commit()
                    logger.info("source='%s' progress=%d/%d", source, i + 1, len(rows))

            db.commit()
            logger.info(
                "source='%s' enriched=%d closed=%d errors=%d",
                source, stats[source], stats["closed"], stats["errors"],
            )

    logger.info("Enrichment finished | stats=%s", stats)
    return stats


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Enrich job descriptions from individual vacancy pages")
    p.add_argument(
        "--sources",
        nargs="+",
        default=None,
        choices=list(_SELECTORS.keys()),
        help="Sources to enrich. Defaults to all: djinni dou workua nofluffjobs",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help=f"Max records per source (default: {BATCH_SIZE})",
    )
    return p


def main() -> None:
    args = build_parser().parse_args()
    stats = run_enrichment(sources=args.sources, limit=args.limit)
    print("Enrichment completed.")
    for key, value in stats.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
