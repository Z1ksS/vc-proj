from __future__ import annotations

import json
import logging
import time

from models.job import Job
from .base import BaseParser

logger = logging.getLogger("job_vc.epam")

_CAREERS_URL = "https://careers.epam.ua/"
_API_URL = "https://careers.epam.ua/api/jobs"
_COMPANY = "EPAM"
_PAGE_SIZE = 100


class EpamParser(BaseParser):
    """
    Scrapes careers.epam.ua — protected by Cloudflare, requires Playwright.
    Install browser: `playwright install chromium`
    """

    def __init__(self) -> None:
        super().__init__()
        self._cache: list[Job] | None = None

    def parse(self, keyword: str) -> list[Job]:
        if self._cache is None:
            self._cache = self._fetch_all()
        return self._cache

    def _fetch_all(self) -> list[Job]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.error("epam: playwright not installed — run `pip install playwright && playwright install chromium`")
            return []

        jobs: list[Job] = []
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                ctx = browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    )
                )
                page = ctx.new_page()

                # Land on the main page to acquire Cloudflare cookies
                page.goto(_CAREERS_URL, wait_until="networkidle", timeout=60_000)
                time.sleep(2)

                page_index = 0
                while True:
                    api_resp = page.evaluate(
                        """async ({url, pageSize, pageIndex}) => {
                            const r = await fetch(url + '?pageSize=' + pageSize + '&pageIndex=' + pageIndex, {
                                credentials: 'include',
                                headers: { 'Accept': 'application/json' }
                            });
                            return r.ok ? r.json() : null;
                        }""",
                        {"url": _API_URL, "pageSize": _PAGE_SIZE, "pageIndex": page_index},
                    )

                    if not api_resp:
                        logger.warning("epam: API returned null at pageIndex=%d", page_index)
                        break

                    items = api_resp.get("data", []) or []
                    if not items:
                        break

                    for item in items:
                        job_id = str(item.get("id", ""))
                        title = (item.get("name") or "").strip()
                        if not title:
                            continue
                        link = f"https://careers.epam.ua/job/{job_id}" if job_id else _CAREERS_URL
                        location_parts = []
                        for loc in item.get("locations") or []:
                            city = loc.get("city") or ""
                            country = loc.get("country") or ""
                            if city or country:
                                location_parts.append(", ".join(x for x in [city, country] if x))
                        location = "; ".join(location_parts)

                        jobs.append(Job(
                            id=link,
                            title=title,
                            company=_COMPANY,
                            salary="Not specified",
                            link=link,
                            job_format=location,
                        ))

                    total = api_resp.get("total", 0)
                    if (page_index + 1) * _PAGE_SIZE >= total:
                        break
                    page_index += 1

                browser.close()
        except Exception:
            logger.exception("epam: Playwright scraping failed")

        logger.info("epam: fetched %d jobs", len(jobs))
        return jobs
