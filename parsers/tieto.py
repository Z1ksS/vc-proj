from __future__ import annotations

import logging

from models.job import Job
from .base import BaseParser

logger = logging.getLogger("job_vc.tieto")

_SR_API = "https://api.smartrecruiters.com/v1/companies/Tieto2/postings"
_JOB_BASE = "https://jobs.smartrecruiters.com/Tieto2"
_COMPANY = "Tieto"
_PAGE_SIZE = 100


class TietoParser(BaseParser):
    """
    Scrapes Tieto vacancies via the SmartRecruiters public API (company=Tieto2).
    The careers.tieto.com Attrax frontend shares the same job database via SR.
    """

    def __init__(self) -> None:
        super().__init__()
        self._cache: list[Job] | None = None

    def parse(self, keyword: str) -> list[Job]:
        if self._cache is None:
            self._cache = self._fetch_all()
        return self._cache

    def _fetch_all(self) -> list[Job]:
        jobs: list[Job] = []
        seen_ids: set[str] = set()
        offset = 0

        while True:
            resp = self._get(
                _SR_API,
                params={"limit": _PAGE_SIZE, "offset": offset},
                timeout=30,
            )
            if resp is None:
                logger.warning("tieto: SR API request failed at offset=%d", offset)
                break

            try:
                data = resp.json()
            except Exception:
                logger.warning("tieto: non-JSON response at offset=%d", offset)
                break

            items = data.get("content", [])
            if not items:
                break

            for item in items:
                job_id = str(item.get("id", ""))
                if not job_id or job_id in seen_ids:
                    continue
                seen_ids.add(job_id)

                title = (item.get("name") or "").strip()
                if not title:
                    continue

                link = f"{_JOB_BASE}/{job_id}"

                loc = item.get("location") or {}
                city = loc.get("city") or ""
                country_code = loc.get("country") or ""
                full_loc = loc.get("fullLocation") or ", ".join(x for x in [city, country_code.upper()] if x)

                work_type_parts = []
                if loc.get("remote"):
                    work_type_parts.append("Remote")
                elif loc.get("hybrid"):
                    work_type_parts.append("Hybrid")

                emp = item.get("typeOfEmployment") or {}
                emp_label = emp.get("label") or ""

                job_format = ", ".join(x for x in [full_loc] + work_type_parts + [emp_label] if x)

                jobs.append(Job(
                    id=link,
                    title=title,
                    company=_COMPANY,
                    salary="Not specified",
                    link=link,
                    job_format=job_format,
                ))

            total = data.get("totalFound", 0)
            offset += len(items)
            if offset >= total:
                break

        logger.info("tieto: fetched %d jobs (total=%d)", len(jobs), total if "total" in dir() else 0)
        return jobs
