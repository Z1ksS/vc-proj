from __future__ import annotations

import logging

import requests

from models.job import Job
from .base import BaseParser

logger = logging.getLogger("job_vc.robotaua")

_BASE_SITE = "https://robota.ua"
_API_URL = "https://api.robota.ua/vacancy/search"
_PAGE_SIZE = 20
_MAX_PAGES = 50

_API_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "uk-UA,uk;q=0.9,en-US;q=0.8",
    "Content-Type": "application/json",
    "Origin": _BASE_SITE,
    "Referer": f"{_BASE_SITE}/jobs/",
}


class RobotauaParser(BaseParser):
    def parse(self, keyword: str) -> list[Job]:
        if not keyword:
            return []

        jobs: list[Job] = []
        seen_ids: set[str] = set()

        for page in range(_MAX_PAGES):
            payload = {
                "keyWords": keyword,
                "page": page,
                "period": 0,
                "regionId": 0,
                "rubricIds": [],
                "subrubricIds": [],
                "cityId": 0,
                "sort": 0,
                "salary": 0,
                "scheduleId": 0,
                "experienceIds": [],
                "languageIds": [],
            }
            try:
                resp = self.session.post(_API_URL, json=payload, headers=_API_HEADERS, timeout=30)
                resp.raise_for_status()
            except requests.RequestException as exc:
                logger.warning("robotaua: request failed page=%d keyword=%r: %s", page, keyword, exc)
                break

            try:
                data = resp.json()
            except Exception:
                logger.warning("robotaua: non-JSON response page=%d keyword=%r", page, keyword)
                break

            documents = data.get("documents", [])
            if not documents:
                break

            for doc in documents:
                job_id = str(doc.get("id", ""))
                if not job_id or job_id in seen_ids:
                    continue
                seen_ids.add(job_id)

                title = (doc.get("name") or "").strip()
                if not title:
                    continue

                company = (doc.get("companyName") or "").strip()
                salary_raw = (doc.get("salaryComment") or "").strip()
                if not salary_raw:
                    salary_num = doc.get("salary")
                    salary_raw = str(salary_num) if salary_num else ""
                location = (doc.get("cityName") or "").strip()
                link = f"{_BASE_SITE}/job/{job_id}"

                jobs.append(Job(
                    id=f"robotaua::{job_id}",
                    title=title,
                    company=company,
                    salary=salary_raw or "Not specified",
                    link=link,
                    job_format=location,
                ))

            total = data.get("total", 0)
            if len(documents) < _PAGE_SIZE or len(seen_ids) >= total:
                break

        logger.info("robotaua: keyword=%r total=%d", keyword, len(jobs))
        return jobs
