from __future__ import annotations

import re
from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from app.models import JobRecord, Technology, VacancyTechnology

_ROLES = ['Backend', 'Frontend', 'DevOps', 'Data', 'QA', 'Mobile', 'Security', 'PM', 'Support', 'Hardware']

_ROLE_COLORS = {
    'Backend':  '#4493f8',
    'Frontend': '#56d364',
    'DevOps':   '#e3b341',
    'Data':     '#bc8cff',
    'QA':       '#ff7b72',
    'Mobile':   '#39c5cf',
    'Security': '#f78166',
    'PM':       '#ffa657',
    'Support':  '#a5d6ff',
    'Hardware': '#7ee787',
}

_ROLE_MAP = [
    # specific roles first to avoid false positives
    ('Security',  ['security engineer', 'security analyst', 'penetration tester', 'pentester',
                   'information security', 'devsecops', 'soc analyst', 'cybersecurity',
                   'appsec', 'security researcher', 'application security']),
    ('DevOps',    ['devops', 'sre ', 'site reliability', 'platform engineer', 'cloud engineer',
                   'infrastructure engineer', 'mlops engineer']),
    ('Data',      ['data engineer', 'data scientist', 'machine learning engineer', 'ml engineer',
                   'data analyst', 'analytics engineer', 'bi developer', 'data platform',
                   'mlops', 'llm engineer', 'ai engineer', 'computer vision']),
    ('Mobile',    ['ios developer', 'ios engineer', 'android developer', 'android engineer',
                   'mobile developer', 'mobile engineer', 'flutter', 'react native developer']),
    ('QA',        ['qa engineer', 'qa automation', 'quality assurance', 'test engineer',
                   'manual tester', 'automation tester', 'sdet', 'test automation engineer', 'qa lead']),
    ('Hardware',  ['hardware engineer', 'embedded', 'fpga', 'firmware engineer',
                   'electronics engineer', 'pcb', 'verilog', 'rtos engineer']),
    ('PM',        ['product manager', 'project manager', 'product owner', 'scrum master',
                   'program manager', 'delivery manager', 'agile coach']),
    ('Support',   ['technical support', 'tech support', 'customer support', 'helpdesk',
                   'support engineer', 'it support', 'system administrator', 'sysadmin',
                   'it administrator', 'service desk']),
    ('Frontend',  ['frontend', 'front-end', 'front end', 'ui developer', 'ui engineer',
                   'react developer', 'vue developer', 'angular developer']),
    # Backend last — broadest catch-all
    ('Backend',   ['backend', 'back-end', 'back end', 'python developer', 'java developer',
                   'golang developer', 'go developer', 'php developer', 'node.js developer',
                   'c# developer', '.net developer', 'ruby developer', 'kotlin developer',
                   'scala developer', 'rust developer', 'c++ developer', 'software engineer',
                   'software developer', 'fullstack', 'full-stack', 'full stack']),
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
    from datetime import datetime, timezone as _tz
    today_start = datetime.now(_tz.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    total = db.execute(select(func.count(JobRecord.id))).scalar_one()
    opened = db.execute(
        select(func.count(JobRecord.id)).where(JobRecord.closed_at.is_(None))
    ).scalar_one()
    closed = total - opened
    with_tech = db.execute(
        select(func.count(VacancyTechnology.vacancy_id.distinct()))
    ).scalar_one()
    with_salary = db.execute(
        select(func.count(JobRecord.id)).where(JobRecord.salary_min.isnot(None))
    ).scalar_one()
    graded = db.execute(
        select(func.count(JobRecord.id)).where(JobRecord.grade.isnot(None))
    ).scalar_one()
    new_today = db.execute(
        select(func.count(JobRecord.id)).where(JobRecord.created_at >= today_start)
    ).scalar_one()
    total_assignments = db.execute(
        select(func.count(VacancyTechnology.vacancy_id))
    ).scalar_one()
    companies = db.execute(
        select(func.count(JobRecord.company.distinct()))
    ).scalar_one()
    avg_stack = round(total_assignments / with_tech, 1) if with_tech else 0
    return {
        "total": total,
        "opened": opened,
        "closed": closed,
        "with_tech": with_tech,
        "with_salary": with_salary,
        "graded": graded,
        "new_today": new_today,
        "avg_stack": avg_stack,
        "companies": companies,
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


def daily_vacancy_counts(db: Session, days: int = 91, status: str = 'all') -> list[dict]:
    from datetime import datetime, timedelta, timezone as _tz
    now = datetime.now(_tz.utc)
    cutoff = now - timedelta(days=days)
    stmt = select(JobRecord.created_at).where(JobRecord.created_at >= cutoff)
    if status == 'open':
        stmt = stmt.where(JobRecord.closed_at.is_(None))
    elif status == 'closed':
        stmt = stmt.where(JobRecord.closed_at.isnot(None))
    rows = db.execute(stmt).fetchall()
    counts: dict[str, int] = defaultdict(int)
    for (created_at,) in rows:
        dt = created_at if created_at.tzinfo else created_at.replace(tzinfo=_tz.utc)
        counts[dt.strftime('%Y-%m-%d')] += 1
    result = []
    for i in range(days):
        day = (now - timedelta(days=days - 1 - i)).date()
        day_str = day.strftime('%Y-%m-%d')
        result.append({'date': day_str, 'count': counts.get(day_str, 0)})
    return result


def weekly_vacancy_counts(db: Session, weeks: int = 16) -> list[int]:
    from datetime import datetime, timedelta, timezone as _tz
    now = datetime.now(_tz.utc)
    cutoff = now - timedelta(weeks=weeks)
    rows = db.execute(
        select(JobRecord.created_at).where(JobRecord.created_at >= cutoff)
    ).fetchall()
    counts = [0] * weeks
    for (created_at,) in rows:
        dt = created_at if created_at.tzinfo else created_at.replace(tzinfo=_tz.utc)
        wk = int((now - dt).total_seconds() / 604800)
        slot = weeks - 1 - min(wk, weeks - 1)
        if 0 <= slot < weeks:
            counts[slot] += 1
    return counts


def tech_cooccurrence(
    db: Session, min_count: int = 10, limit: int = 40
) -> list[tuple[str, str, int, float]]:
    total_with_tech = db.execute(
        select(func.count(VacancyTechnology.vacancy_id.distinct()))
    ).scalar_one() or 1
    tech_counts = dict(db.execute(
        select(Technology.name, func.count(VacancyTechnology.vacancy_id).label("cnt"))
        .join(VacancyTechnology, VacancyTechnology.tech_id == Technology.id)
        .group_by(Technology.name)
    ).fetchall())

    vt1 = aliased(VacancyTechnology, name="vt1")
    vt2 = aliased(VacancyTechnology, name="vt2")
    t1 = aliased(Technology, name="t1")
    t2 = aliased(Technology, name="t2")
    rows = db.execute(
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

    result = []
    for tech1, tech2, cnt in rows:
        cnt_a = tech_counts.get(tech1, 1)
        cnt_b = tech_counts.get(tech2, 1)
        lift = round((cnt * total_with_tech) / (cnt_a * cnt_b), 1)
        result.append((tech1, tech2, cnt, lift))
    return result


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


def source_grade_mix(db: Session) -> dict[str, dict[str, int]]:
    rows = db.execute(
        select(JobRecord.source, JobRecord.grade, func.count(JobRecord.id))
        .where(JobRecord.grade.isnot(None))
        .group_by(JobRecord.source, JobRecord.grade)
    ).fetchall()
    result: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for source, grade, cnt in rows:
        result[source][grade] = cnt
    return {s: dict(g) for s, g in result.items()}


def salary_histogram(db: Session) -> dict:
    BUCKETS = 30
    MAX_SAL = 15000
    rows = db.execute(
        select(JobRecord.salary_min, JobRecord.salary_max)
        .where(JobRecord.salary_min.isnot(None))
        .where(JobRecord.salary_min > 100)
    ).fetchall()
    hist = [0] * BUCKETS
    for sal_min, sal_max in rows:
        mid = sal_min + (sal_max - sal_min) // 2 if sal_max else sal_min
        idx = min(BUCKETS - 1, int(mid / MAX_SAL * BUCKETS))
        hist[idx] += 1
    return {'hist': hist, 'total': len(rows), 'max_sal': MAX_SAL}


def salary_by_grade(db: Session) -> dict[str, dict]:
    rows = db.execute(
        select(JobRecord.grade, JobRecord.salary_min, JobRecord.salary_max)
        .where(JobRecord.grade.isnot(None))
        .where(JobRecord.salary_min.isnot(None))
        .where(JobRecord.salary_min > 100)
    ).fetchall()
    grade_sals: dict[str, list[int]] = defaultdict(list)
    for grade, sal_min, sal_max in rows:
        mid = sal_min + (sal_max - sal_min) // 2 if sal_max else sal_min
        grade_sals[grade].append(mid)
    result: dict[str, dict] = {}
    for grade, values in grade_sals.items():
        if len(values) < 3:
            continue
        vals = sorted(values)
        n = len(vals)
        result[grade] = {
            'n': n,
            'p25': vals[int(n * 0.25)],
            'median': vals[int(n * 0.50)],
            'p75': vals[int(n * 0.75)],
            'min': vals[0],
            'max': vals[-1],
        }
    return result


def salary_by_role(db: Session) -> dict[str, dict]:
    rows = db.execute(
        select(JobRecord.normalized_title, JobRecord.salary_min, JobRecord.salary_max)
        .where(JobRecord.salary_min.isnot(None))
        .where(JobRecord.salary_min > 100)
    ).fetchall()
    role_sals: dict[str, list[int]] = defaultdict(list)
    for title, sal_min, sal_max in rows:
        role = _classify_role(title or '')
        if role:
            mid = sal_min + (sal_max - sal_min) // 2 if sal_max else sal_min
            role_sals[role].append(mid)
    result: dict[str, dict] = {}
    for role, values in role_sals.items():
        if len(values) < 3:
            continue
        vals = sorted(values)
        n = len(vals)
        result[role] = {
            'n': n,
            'p25': vals[int(n * 0.25)],
            'median': vals[int(n * 0.50)],
            'p75': vals[int(n * 0.75)],
            'min': vals[0],
            'max': vals[-1],
            'color': _ROLE_COLORS.get(role, '#7d8590'),
        }
    return result


def role_category_stats(db: Session) -> dict[str, int]:
    rows = db.execute(select(JobRecord.title)).fetchall()
    counts: dict[str, int] = defaultdict(int)
    total = 0
    for (title,) in rows:
        total += 1
        role = _classify_role(title or '')
        if role:
            counts[role] += 1
    result = {r: counts.get(r, 0) for r in _ROLES}
    result['Other'] = total - sum(counts.values())
    return result


def top_job_titles(db: Session, limit: int = 60) -> list[dict]:
    rows = db.execute(select(JobRecord.id, JobRecord.title)).fetchall()
    title_ids: dict[str, list[int]] = defaultdict(list)
    for job_id, title in rows:
        norm = _normalize_role(title or '')
        if norm:
            title_ids[norm].append(job_id)

    top = sorted(title_ids.items(), key=lambda x: -len(x[1]))[:limit]
    all_ids = [jid for _, ids in top for jid in ids]
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
    for title, job_ids in top:
        tech_counter: dict[str, int] = defaultdict(int)
        for jid in job_ids:
            for tech in vac_techs[jid]:
                tech_counter[tech] += 1
        top_techs = sorted(tech_counter.items(), key=lambda x: -x[1])[:5]
        result.append({'title': title, 'count': len(job_ids), 'techs': [[t, c] for t, c in top_techs]})
    return result


def top_tech_counts(db: Session, limit: int = 20) -> dict[str, int]:
    return dict(db.execute(
        select(Technology.name, func.count(VacancyTechnology.vacancy_id).label("cnt"))
        .join(VacancyTechnology, VacancyTechnology.tech_id == Technology.id)
        .group_by(Technology.name)
        .order_by(func.count(VacancyTechnology.vacancy_id).desc())
        .limit(limit)
    ).fetchall())


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
