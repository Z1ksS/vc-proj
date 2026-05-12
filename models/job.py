from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Job:
    id: str
    title: str
    company: str
    salary: str
    link: str
    job_format: str
    description: str | None = field(default=None)
    