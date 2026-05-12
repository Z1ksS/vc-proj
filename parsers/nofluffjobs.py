import json

from models.job import Job
from .base import BaseParser


class NoFluffJobsParser(BaseParser):
    def parse(self, keyword: str) -> list[Job]:
        url = (
            "https://nofluffjobs.com/api/search/posting?"
            "withSalaryMatch=true&salaryCurrency=UAH&salaryPeriod=month&region=ua&language=uk-UA"
        )
        headers = {
            "Content-Type": "application/infiniteSearch+json",
            "User-Agent": "Mozilla/5.0",
            "Origin": "https://nofluffjobs.com",
            "Referer": "https://nofluffjobs.com/ua/",
            "nfj-global-context": json.dumps({"region": "UA", "lang": "uk"}),
        }
        body = {
            "criteria": "",
            "url": {"searchParam": keyword},
            "rawSearch": keyword,
            "pageSize": 60,
            "withSalaryMatch": True,
        }

        resp = self._post(url, headers=headers, json=body)
        if resp is None:
            return []
        try:
            data = resp.json()
        except ValueError:
            return []
        postings = data.get("postings", [])
        if not postings:
            return []

        jobs: list[Job] = []
        seen_vacancies: set[str] = set()

        for post in postings:
            title = (post.get("title") or "").strip()
            company = (post.get("name") or "").strip()
            if not title or not company:
                continue

            dedupe_key = f"{title.lower()}::{company.lower()}"
            if dedupe_key in seen_vacancies:
                continue
            seen_vacancies.add(dedupe_key)

            salary = "Not specified"
            salary_data = post.get("salary") or {}
            if salary_data.get("from") is not None:
                salary = f"{salary_data.get('from')} - {salary_data.get('to')} {salary_data.get('currency')}"

            link = "https://nofluffjobs.com/ua/job/" + (post.get("url") or "")
            jobs.append(
                Job(
                    id=f"{company}::{link}",
                    title=title,
                    company=company,
                    salary=salary,
                    link=link,
                    job_format="",
                )
            )

        return jobs

