import time
from urllib.parse import quote

from bs4 import BeautifulSoup

from models.job import Job
from .base import BaseParser

_MAX_PAGES = 50


class WorkUaParser(BaseParser):
    def get_last_page_number(self, base_url: str) -> int:
        response = self._get(base_url.format(1))
        if response is None:
            return 1
        soup = BeautifulSoup(response.text, "lxml")
        pagination = soup.select("ul.pagination li a")
        if not pagination:
            return 1

        page_numbers: list[int] = []
        for link in pagination:
            href = link.get("href", "")
            if "page=" in href:
                try:
                    page = int(href.split("page=")[1].split("&")[0])
                    page_numbers.append(page)
                except Exception:
                    continue
        return max(page_numbers) if page_numbers else 1

    def parse(self, keyword: str) -> list[Job]:
        query = quote(keyword.lower(), safe="")
        base_url = f"https://www.work.ua/jobs-it-{query}/?page={{}}"
        last_page = min(self.get_last_page_number(base_url), _MAX_PAGES)
        results: list[Job] = []

        for page in range(1, last_page + 1):
            if page > 1:
                time.sleep(1.0)
            response = self._get(base_url.format(page))
            if response is None:
                continue
            soup = BeautifulSoup(response.text, "lxml")
            items = soup.select("div.card.job-link")

            for item in items:
                title_el = item.select_one("h2 > a")
                company_el = item.select_one("div.mt-xs span.strong-600")
                salary_el = item.select_one("span.strong-600")

                title = title_el.get_text(strip=True) if title_el else "Unknown"
                company = company_el.get_text(strip=True) if company_el else "Unknown"
                salary = salary_el.get_text(strip=True) if salary_el else "Not specified"
                link = f"https://www.work.ua{title_el.get('href')}" if title_el else ""

                results.append(
                    Job(
                        id=f"{company}::{link}",
                        title=title,
                        company=company,
                        salary=salary,
                        link=link,
                        job_format="",
                    )
                )

        return results

