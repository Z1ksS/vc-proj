from __future__ import annotations

import logging

from bs4 import BeautifulSoup

from models.job import Job
from .base import BaseParser

logger = logging.getLogger("job_vc.sigma")

_AJAX_URL = "https://career.sigma.software/wp-admin/admin-ajax.php"
_SITEMAP_URL = "https://career.sigma.software/vacancy-sitemap.xml"
_BASE_URL = "https://career.sigma.software"
_COMPANY = "Sigma Software"
_HEADERS = {
    "Content-Type": "application/x-www-form-urlencoded",
    "Referer": "https://career.sigma.software/what-we-offer/vacancies/",
    "Origin": "https://career.sigma.software",
}
_MAX_PAGES = 50


class SigmaParser(BaseParser):
    """Scrapes career.sigma.software via WordPress AJAX filter_vacancies_v2.

    The AJAX API caps pagination at ~55 results even though 63 jobs exist.
    The sitemap is used to discover the remaining URLs, which are then fetched
    individually.
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
        seen_links: set[str] = set()

        # Primary source: AJAX filter API
        resp = self._post(
            _AJAX_URL,
            headers=_HEADERS,
            data={
                "action": "filter_vacancies_v2",
                "keyword": "",
                "direction": "[]",
                "direction_type": "OR",
                "locations": "[]",
                "seniority": "[]",
                "workplace_type": "[]",
            },
            timeout=30,
        )
        if resp is None:
            logger.warning("sigma: initial request failed")
            return []

        try:
            result = resp.json()
        except Exception:
            logger.warning("sigma: initial response is not JSON")
            return []

        if not result.get("success"):
            logger.warning("sigma: API returned success=false")
            return []

        data = result.get("data", {})
        jobs.extend(self._extract_cards(data.get("html", ""), seen_links))

        page = 2
        while data.get("has_more") and page <= _MAX_PAGES:
            resp = self._post(
                _AJAX_URL,
                headers=_HEADERS,
                data={
                    "action": "filter_vacancies_v2_loadmore",
                    "page": str(page),
                    "direction": "[]",
                    "direction_type": "OR",
                    "locations": "[]",
                    "seniority": "[]",
                    "workplace_type": "[]",
                    "keyword": "",
                },
                timeout=30,
            )
            if resp is None:
                logger.warning("sigma: load-more request failed at page=%d", page)
                break

            try:
                result = resp.json()
            except Exception:
                logger.warning("sigma: load-more non-JSON at page=%d", page)
                break

            if not result.get("success"):
                break

            data = result.get("data", {})
            jobs.extend(self._extract_cards(data.get("html", ""), seen_links))
            page += 1

        # Supplement with sitemap to catch jobs the API pagination misses
        sitemap_urls = self._fetch_sitemap_urls()
        missing = [u for u in sitemap_urls if u not in seen_links]
        if missing:
            logger.info("sigma: fetching %d jobs missed by API pagination", len(missing))
            for url in missing:
                job = self._fetch_job_page(url)
                if job:
                    jobs.append(job)
                    seen_links.add(url)

        logger.info("sigma: fetched %d jobs total", len(jobs))
        return jobs

    def _fetch_sitemap_urls(self) -> list[str]:
        resp = self._get(_SITEMAP_URL, timeout=30)
        if resp is None:
            logger.warning("sigma: sitemap request failed")
            return []
        try:
            soup = BeautifulSoup(resp.text, "xml")
            return [loc.text.strip() for loc in soup.find_all("loc")]
        except Exception:
            logger.warning("sigma: sitemap parse failed")
            return []

    def _fetch_job_page(self, url: str) -> Job | None:
        resp = self._get(url, timeout=30)
        if resp is None:
            return None
        soup = BeautifulSoup(resp.text, "lxml")

        h1 = soup.select_one("h1")
        title = h1.get_text(strip=True) if h1 else ""
        if not title:
            return None

        loc_el = soup.select_one(".vacancy-card-new__locations span")
        location = loc_el.get_text(strip=True) if loc_el else ""
        if not location:
            for el in soup.select("[class*=location]"):
                txt = el.get_text(strip=True)
                if txt and "choose" not in txt.lower():
                    location = txt
                    break

        workplace_el = soup.select_one(".vacancy-card__workplace")
        workplace = workplace_el.get_text(strip=True) if workplace_el else ""

        seniority_el = soup.select_one(".vacancy-card__seniority")
        seniority = seniority_el.get_text(strip=True) if seniority_el else ""

        job_format = ", ".join(x for x in [seniority, workplace, location] if x)

        return Job(
            id=url,
            title=title,
            company=_COMPANY,
            salary="Not specified",
            link=url,
            job_format=job_format,
        )

    def _extract_cards(self, html: str, seen: set[str]) -> list[Job]:
        soup = BeautifulSoup(html, "lxml")
        jobs: list[Job] = []
        for card in soup.select("a.vacancy-card-new"):
            link = card.get("href", "").strip()
            if not link or link in seen:
                continue
            seen.add(link)

            title_el = card.select_one("h3.vacancy-card-new__title")
            title_parts = []
            if title_el:
                for part in title_el.strings:
                    t = part.strip()
                    if t:
                        title_parts.append(t)
            title = " ".join(title_parts)
            if not title:
                continue

            loc_el = card.select_one(".vacancy-card-new__locations span")
            location = loc_el.get_text(strip=True) if loc_el else ""

            workplace_el = card.select_one(".vacancy-card__workplace")
            seniority_el = card.select_one(".vacancy-card__seniority")
            job_format_parts = [
                x for x in [
                    seniority_el.get_text(strip=True) if seniority_el else "",
                    workplace_el.get_text(strip=True) if workplace_el else "",
                    location,
                ] if x
            ]

            jobs.append(Job(
                id=link,
                title=title,
                company=_COMPANY,
                salary="Not specified",
                link=link,
                job_format=", ".join(job_format_parts),
            ))
        return jobs
