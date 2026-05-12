from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup

from models.job import Job
from .base import BaseParser

logger = logging.getLogger("job_vc.dou")

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "uk-UA,uk;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://jobs.dou.ua/",
}
_XHR_HEADERS = {
    **_HEADERS,
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "X-Requested-With": "XMLHttpRequest",
}

_BASE_URL = "https://jobs.dou.ua/vacancies/"
_XHR_PATH = "https://jobs.dou.ua/vacancies/xhr-load/"
_CSRF_RE = re.compile(r"window\.CSRF_TOKEN\s*=\s*['\"]([^'\"]+)['\"]")
_MAX_PAGES = 50  # safety cap (~1000 vacancies)


class DouParser(BaseParser):
    def parse(self, keyword: str) -> list[Job]:
        if not keyword:
            return []

        # Step 1: load the first page — seeds session cookie (csrftoken) + initial vacancies
        first = self._get(_BASE_URL, params={"category": keyword}, headers=_HEADERS, timeout=30)
        if first is None:
            logger.warning("dou: initial request failed keyword=%r", keyword)
            return []

        soup = BeautifulSoup(first.text, "lxml")
        jobs = self._extract_jobs(soup)
        seen_ids = {j.id for j in jobs}
        count = len(jobs)

        # Step 2: get CSRF token (from inline JS, fall back to session cookie)
        csrf = _CSRF_RE.search(first.text)
        csrf_token = csrf.group(1) if csrf else self.session.cookies.get("csrftoken", "")
        if not csrf_token:
            logger.warning("dou: no CSRF token, returning first page only (%d jobs)", count)
            return jobs

        # Step 3: paginate via the XHR endpoint the site uses internally
        xhr_url = f"{_XHR_PATH}?category={keyword}"
        xhr_headers = {**_XHR_HEADERS, "Referer": f"{_BASE_URL}?category={keyword}"}

        for _ in range(_MAX_PAGES):
            resp = self._post(
                xhr_url,
                headers=xhr_headers,
                data={"csrfmiddlewaretoken": csrf_token, "count": count},
                timeout=30,
            )
            if resp is None:
                logger.warning("dou: XHR request failed at count=%d", count)
                break

            try:
                data = resp.json()
            except Exception:
                logger.warning("dou: XHR non-JSON response at count=%d (status=%s)", count, resp.status_code)
                break

            if data.get("error"):
                break

            page_jobs = self._extract_jobs(BeautifulSoup(data.get("html", ""), "lxml"))
            new_jobs = [j for j in page_jobs if j.id not in seen_ids]
            seen_ids.update(j.id for j in new_jobs)
            jobs.extend(new_jobs)
            count += data.get("num", len(page_jobs))

            if data.get("last", True):
                break

        logger.info("dou: keyword=%r total=%d", keyword, len(jobs))
        return jobs

    def _extract_jobs(self, soup: BeautifulSoup) -> list[Job]:
        jobs: list[Job] = []
        for item in soup.find_all("li", class_="l-vacancy"):
            title_el = item.select_one("a.vt")
            company_el = item.select_one("a.company")
            salary_el = item.select_one("span.salary")
            location_el = item.select_one("span.cities")

            title = title_el.text.strip() if title_el else ""
            if not title:
                continue

            company = company_el.text.strip() if company_el else ""
            salary = salary_el.text.strip() if salary_el else "Not specified"
            link = title_el.get("href", "") if title_el else ""
            job_format = location_el.text.strip() if location_el else ""

            jobs.append(Job(
                id=f"{company}::{link}",
                title=title,
                company=company,
                salary=salary,
                link=link,
                job_format=job_format,
            ))
        return jobs
