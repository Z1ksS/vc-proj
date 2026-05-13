from __future__ import annotations

import re
from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from app.models import JobRecord, Technology, VacancyTechnology

_ROLES = ['Backend', 'Frontend', 'DevOps', 'Data', 'QA', 'Mobile']

_ROLE_COLORS = {
    'Backend':  '#4493f8',
    'Frontend': '#56d364',
    'DevOps':   '#e3b341',
    'Data':     '#bc8cff',
    'QA':       '#ff7b72',
    'Mobile':   '#39c5cf',
}

_ROLE_MAP = [
    ('DevOps',   ['devops', 'sre ', 'site reliability', 'platform engineer', 'cloud engineer', 'infrastructure engineer', 'devsecops', 'mlops engineer']),
    ('Data',     ['data engineer', 'data scientist', 'machine learning engineer', 'ml engineer', 'data analyst', 'analytics engineer', 'bi developer', 'data platform', 'mlops']),
    ('Mobile',   ['ios developer', 'ios engineer', 'android developer', 'android engineer', 'mobile developer', 'mobile engineer', 'flutter', 'react native developer']),
    ('QA',       ['qa engineer', 'qa automation', 'quality assurance', 'test engineer', 'manual tester', 'automation tester', 'sdet', 'test automation engineer']),
    ('Frontend', ['frontend', 'front-end', 'front end', 'ui developer', 'ui engineer']),
    ('Backend',  ['backend', 'back-end', 'back end', 'python developer', 'java developer', 'golang developer', 'go developer', 'php developer', 'node.js developer', 'c# developer', '.net developer']),
]


def _classify_role(title: str) -> str | None:
    t = ' ' + title.lower() + ' '
    for role, keywords in _ROLE_MAP:
        if any(kw in t for kw in keywords):
            return role
    return None


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


def tech_analytics_data(db: Session) -> dict:
    jobs = db.execute(
        select(JobRecord.id, JobRecord.source, JobRecord.grade, JobRecord.normalized_title)
    ).fetchall()

    job_roles: dict[int, str] = {}
    role_totals: dict[str, int] = defaultdict(int)
    for job_id, source, grade, title in jobs:
        role = _classify_role(title or '')
        if role:
            job_roles[job_id] = role
            role_totals[role] += 1

    tech_rows = db.execute(
        select(VacancyTechnology.vacancy_id, Technology.name)
        .join(Technology, Technology.id == VacancyTechnology.tech_id)
    ).fetchall()

    tech_role: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    tech_total: dict[str, int] = defaultdict(int)
    for vac_id, tech_name in tech_rows:
        tech_total[tech_name] += 1
        role = job_roles.get(vac_id)
        if role:
            tech_role[tech_name][role] += 1

    sorted_techs = sorted(tech_total.items(), key=lambda x: -x[1])

    techs_raw = {}
    for tech, _ in sorted_techs[:60]:
        counts = tech_role.get(tech, {})
        techs_raw[tech] = [counts.get(r, 0) for r in _ROLES]

    total = len(jobs)
    top_tech, top_tech_cnt = sorted_techs[0] if sorted_techs else ('N/A', 0)
    with_tech_count = db.execute(
        select(func.count(VacancyTechnology.vacancy_id.distinct()))
    ).scalar_one()
    total_assignments = db.execute(
        select(func.count(VacancyTechnology.vacancy_id))
    ).scalar_one()
    avg_stack = round(total_assignments / with_tech_count, 1) if with_tech_count else 0

    source_counts = dict(db.execute(
        select(JobRecord.source, func.count(JobRecord.id))
        .group_by(JobRecord.source)
        .order_by(func.count(JobRecord.id).desc())
    ).fetchall())

    grade_counts = dict(db.execute(
        select(JobRecord.grade, func.count(JobRecord.id))
        .where(JobRecord.grade.isnot(None))
        .group_by(JobRecord.grade)
        .order_by(func.count(JobRecord.id).desc())
    ).fetchall())

    return {
        'roles': _ROLES,
        'role_totals': {r: role_totals.get(r, 0) for r in _ROLES},
        'role_colors': _ROLE_COLORS,
        'techs_raw': techs_raw,
        'kpi': {
            'total': total,
            'unique_techs': len(tech_total),
            'top_tech': top_tech,
            'top_tech_cnt': top_tech_cnt,
            'avg_stack': avg_stack,
            'coverage_pct': round(with_tech_count / total * 100) if total else 0,
        },
        'source_counts': source_counts,
        'grade_counts': grade_counts,
    }
