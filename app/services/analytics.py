from __future__ import annotations

import re
from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from app.models import JobRecord, Technology, VacancyTechnology

_GRADE_RE = re.compile(
    r"\b(junior|middle|senior|lead|staff|principal|intern|sr\.?|jr\.?|trainee|стажер)\b",
    re.IGNORECASE,
)
_TRIM_RE = re.compile(r"[/(,].*$")
_WS_RE = re.compile(r"\s+")


def _normalize_role(title: str) -> str:
    t = _TRIM_RE.sub("", title)
    t = _GRADE_RE.sub("", t)
    t = _WS_RE.sub(" ", t).strip()
    return t or title


def summary_stats(db: Session) -> dict:
    total = db.execute(select(func.count(JobRecord.id))).scalar_one()
    with_tech = db.execute(
        select(func.count(VacancyTechnology.vacancy_id.distinct()))
    ).scalar_one()
    with_salary = db.execute(
        select(func.count(JobRecord.id)).where(JobRecord.salary_min.isnot(None))
    ).scalar_one()
    graded = db.execute(
        select(func.count(JobRecord.id)).where(JobRecord.grade.isnot(None))
    ).scalar_one()
    return {
        "total": total,
        "with_tech": with_tech,
        "with_salary": with_salary,
        "graded": graded,
    }


def grade_distribution(db: Session) -> list[tuple[str, int]]:
    rows = db.execute(
        select(JobRecord.grade, func.count(JobRecord.id).label("cnt"))
        .group_by(JobRecord.grade)
        .order_by(func.count(JobRecord.id).desc())
    ).fetchall()
    return [(grade or "—", cnt) for grade, cnt in rows]


def source_distribution(db: Session) -> list[tuple[str, int]]:
    return db.execute(
        select(JobRecord.source, func.count(JobRecord.id).label("cnt"))
        .group_by(JobRecord.source)
        .order_by(func.count(JobRecord.id).desc())
    ).fetchall()


def tech_cooccurrence(
    db: Session, min_count: int = 10, limit: int = 40
) -> list[tuple[str, str, int]]:
    vt1 = aliased(VacancyTechnology, name="vt1")
    vt2 = aliased(VacancyTechnology, name="vt2")
    t1 = aliased(Technology, name="t1")
    t2 = aliased(Technology, name="t2")
    return db.execute(
        select(t1.name.label("tech1"), t2.name.label("tech2"), func.count().label("cnt"))
        .select_from(vt1)
        .join(vt2, (vt2.vacancy_id == vt1.vacancy_id) & (vt2.tech_id > vt1.tech_id))
        .join(t1, t1.id == vt1.tech_id)
        .join(t2, t2.id == vt2.tech_id)
        .group_by(t1.name, t2.name)
        .having(func.count() >= min_count)
        .order_by(func.count().desc())
        .limit(limit)
    ).fetchall()


def role_tech_stats(
    db: Session, min_vacancies: int = 5, limit: int = 80
) -> list[tuple[str, int, list[tuple[str, int]]]]:
    jobs = db.execute(select(JobRecord.id, JobRecord.title)).fetchall()

    role_jobs: dict[str, list[int]] = defaultdict(list)
    for job_id, title in jobs:
        role = _normalize_role(title)
        if role:
            role_jobs[role].append(job_id)

    top_roles = sorted(
        [(role, ids) for role, ids in role_jobs.items() if len(ids) >= min_vacancies],
        key=lambda x: -len(x[1]),
    )[:limit]

    all_ids = [jid for _, ids in top_roles for jid in ids]
    if not all_ids:
        return []

    tech_rows = db.execute(
        select(VacancyTechnology.vacancy_id, Technology.name)
        .join(Technology, Technology.id == VacancyTechnology.tech_id)
        .where(VacancyTechnology.vacancy_id.in_(all_ids))
    ).fetchall()

    vac_techs: dict[int, list[str]] = defaultdict(list)
    for vac_id, tech_name in tech_rows:
        vac_techs[vac_id].append(tech_name)

    result = []
    for role, job_ids in top_roles:
        tech_counter: dict[str, int] = defaultdict(int)
        for jid in job_ids:
            for tech in vac_techs[jid]:
                tech_counter[tech] += 1
        top_techs = sorted(tech_counter.items(), key=lambda x: -x[1])[:5]
        result.append((role, len(job_ids), top_techs))

    return result
