import re
import time
from urllib.parse import quote

from bs4 import BeautifulSoup

from models.job import Job
from .base import BaseParser

_MAX_PAGES = 50


def _extract_text(el) -> str:
    text = el.get_text(separator="\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = "\n".join(line.strip() for line in text.splitlines())
    return text.strip()


class DjinniParser(BaseParser):
    def get_last_page_number(self, base_url: str) -> int:
        response = self._get(base_url.format(1))
        if response is None:
            return 1
        soup = BeautifulSoup(response.text, "lxml")
        links = soup.find_all("a", class_="page-link")
        try:
            digits = [int(a.text) for a in links if a.text.strip().isdigit()]
            return max(digits) if digits else 1
        except Exception:
            return 1

    def parse(self, keyword: str) -> list[Job]:
        if not keyword:
            return []

        encoded = quote(keyword, safe="")
        base_url = f"https://djinni.co/jobs/?primary_keyword={encoded}&page={{}}"
        last_page = min(self.get_last_page_number(base_url), _MAX_PAGES)
        results: list[Job] = []

        for page in range(1, last_page + 1):
            if page > 1:
                time.sleep(1.5)
            response = self._get(base_url.format(page))
            if response is None:
                continue
            soup = BeautifulSoup(response.text, "lxml")
            items = soup.find_all("div", class_="job-item")

            for item in items:
                link_el = item.select_one("a.job_item__header-link")
                title_el = item.select_one("h2.job-item__position")
                company_el = item.select_one("span.small.text-gray-800")
                salary_el = item.select_one("span.text-body-tertiary.fw-medium")
                details_div = item.select_one("div.fw-medium.d-flex.flex-wrap.align-items-center")
                location_el = item.select_one("span.location-text")
                first_span = details_div.select_one("span.text-nowrap") if details_div else None

                title = title_el.text.strip() if title_el else ""
                company = company_el.text.strip() if company_el else ""
                salary = salary_el.text.strip() if salary_el else "Not specified"
                href = link_el.get("href", "") if link_el else ""
                link = f"https://djinni.co{href}" if href else ""
                job_format = (
                    f"{first_span.text.strip()} {location_el.text.strip()}"
                    if first_span and location_el
                    else ""
                )

                if not title or not link:
                    continue

                desc_el = item.select_one("span.js-original-text")
                description = _extract_text(desc_el) if desc_el else None

                results.append(
                    Job(
                        id=f"{company}::{link}",
                        title=title,
                        company=company,
                        salary=salary,
                        link=link,
                        job_format=job_format,
                        description=description,
                    )
                )

        return results
