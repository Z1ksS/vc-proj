from __future__ import annotations

import logging

from bs4 import BeautifulSoup

from models.job import Job
from .base import BaseParser

logger = logging.getLogger("job_vc.provectus")

_BASE_URL = "https://careers.provectus.com/jobs/"
_COMPANY = "Provectus"


class ProvectusParser(BaseParser):
    """Scrapes careers.provectus.com — server-side rendered WordPress site."""

    def __init__(self) -> None:
        super().__init__()
        self._cache: list[Job] | None = None

    def parse(self, keyword: str) -> list[Job]:
        if self._cache is None:
            self._cache = self._fetch_all()
        return self._cache

    def _fetch_all(self) -> list[Job]:
        resp = self._get(_BASE_URL, timeout=30)
        if resp is None:
            logger.warning("provectus: failed to fetch jobs page")
            return []

        soup = BeautifulSoup(resp.text, "lxml")
        jobs: list[Job] = []
        for card in soup.select("div.jobs-vac-col"):
            link_el = card.select_one("a.jobs-vac-a")
            title_el = card.select_one("h3.jobs-vac-title")
            loc_el = card.select_one("div.jobs-vac-location")

            title = title_el.get_text(strip=True) if title_el else ""
            if not title:
                continue

            link = link_el.get("href", "") if link_el else ""
            location = loc_el.get_text(strip=True) if loc_el else ""

            jobs.append(Job(
                id=link,
                title=title,
                company=_COMPANY,
                salary="Not specified",
                link=link,
                job_format=location,
            ))

        logger.info("provectus: fetched %d jobs", len(jobs))
        return jobs
