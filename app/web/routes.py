from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timedelta
from datetime import timezone as _tz
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.db import get_db
from app.ingest import run_ingestion
from app.models import JobRecord, Technology, TrackingCard, VacancyTechnology


router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
templates.env.filters["urlquote"] = lambda s: quote(str(s), safe="")
templates.env.globals["current_user_fn"] = get_current_user


def _reltime(dt) -> str:
    if dt is None:
        return "—"
    now = datetime.now(_tz.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_tz.utc)
    d = (now - dt).days
    if d == 0:
        h = (now - dt).seconds // 3600
        return f"{h}h ago" if h else "just now"
    if d == 1:
        return "1d ago"
    if d < 7:
        return f"{d}d ago"
    if d < 30:
        return f"{d // 7}w ago"
    return f"{d // 30}mo ago"


templates.env.filters["reltime"] = _reltime

_GRADES = ["Junior", "Middle", "Senior", "Lead", "Staff", "Principal", "Intern"]
_PAGE_SIZE = 50

_SORT_MAP = {
    "posted-desc": (JobRecord.created_at.desc(), JobRecord.id.desc()),
    "posted-asc":  (JobRecord.created_at.asc(),  JobRecord.id.asc()),
    "salary-desc": (JobRecord.salary_min.desc(),),
    "salary-asc":  (JobRecord.salary_min.asc(),),
    "title-asc":   (func.lower(JobRecord.title).asc(),),
    "company-asc": (func.lower(JobRecord.company).asc(),),
}


def _apply_filters(
    stmt: Select,
    keyword, source, tech, grade, company,
    sal_min=None, sal_max=None, include_closed=False,
) -> Select:
    if not include_closed:
        stmt = stmt.where(JobRecord.closed_at.is_(None))
    if keyword:
        like = f"%{keyword.lower()}%"
        tech_subq = (
            select(VacancyTechnology.vacancy_id)
            .join(Technology, Technology.id == VacancyTechnology.tech_id)
            .where(func.lower(Technology.name).like(like))
            .scalar_subquery()
        )
        stmt = stmt.where(
            func.lower(JobRecord.title).like(like) |
            func.lower(JobRecord.company).like(like) |
            JobRecord.id.in_(tech_subq)
        )
    if source:
        stmt = stmt.where(JobRecord.source == source)
    if grade:
        stmt = stmt.where(JobRecord.grade == grade)
    if company:
        stmt = stmt.where(JobRecord.company == company)
    if tech:
        tech_subq = (
            select(VacancyTechnology.vacancy_id)
            .join(Technology, Technology.id == VacancyTechnology.tech_id)
            .where(Technology.name == tech)
            .scalar_subquery()
        )
        stmt = stmt.where(JobRecord.id.in_(tech_subq))
    if sal_min:
        stmt = stmt.where(JobRecord.salary_min >= sal_min)
    if sal_max:
        stmt = stmt.where(JobRecord.salary_min <= sal_max)
    return stmt


def _query_jobs(
    keyword=None, source=None, tech=None, grade=None, company=None,
    sal_min=None, sal_max=None, sort="posted-desc", page=1, include_closed=False,
) -> Select:
    order = _SORT_MAP.get(sort, _SORT_MAP["posted-desc"])
    stmt = select(JobRecord).order_by(*order)
    stmt = _apply_filters(stmt, keyword, source, tech, grade, company, sal_min, sal_max, include_closed)
    return stmt.offset((page - 1) * _PAGE_SIZE).limit(_PAGE_SIZE)


def _count_jobs(
    db: Session,
    keyword=None, source=None, tech=None, grade=None, company=None,
    sal_min=None, sal_max=None, include_closed=False,
) -> int:
    stmt = select(func.count(JobRecord.id))
    stmt = _apply_filters(stmt, keyword, source, tech, grade, company, sal_min, sal_max, include_closed)
    return db.execute(stmt).scalar_one()


def _load_tech_map(db: Session, jobs: list) -> dict[int, list[str]]:
    job_ids = [j.id for j in jobs]
    if not job_ids:
        return {}
    tech_map: dict[int, list[str]] = defaultdict(list)
    for vacancy_id, name in db.execute(
        select(VacancyTechnology.vacancy_id, Technology.name)
        .join(Technology, Technology.id == VacancyTechnology.tech_id)
        .where(VacancyTechnology.vacancy_id.in_(job_ids))
        .order_by(Technology.name)
    ).fetchall():
        tech_map[vacancy_id].append(name)
    return tech_map


def _common_context(db: Session) -> dict:
    sources = db.execute(
        select(JobRecord.source, func.count(JobRecord.id).label("cnt"))
        .group_by(JobRecord.source)
        .order_by(func.count(JobRecord.id).desc())
    ).fetchall()
    techs = db.execute(
        select(Technology.name, func.count(VacancyTechnology.vacancy_id).label("cnt"))
        .join(VacancyTechnology, VacancyTechnology.tech_id == Technology.id)
        .group_by(Technology.name)
        .order_by(func.count(VacancyTechnology.vacancy_id).desc())
        .limit(60)
    ).fetchall()
    grade_counts = dict(db.execute(
        select(JobRecord.grade, func.count(JobRecord.id))
        .where(JobRecord.grade.isnot(None))
        .group_by(JobRecord.grade)
        .order_by(func.count(JobRecord.id).desc())
    ).fetchall())
    top_companies = db.execute(
        select(JobRecord.company, func.count(JobRecord.id).label("cnt"))
        .group_by(JobRecord.company)
        .order_by(func.count(JobRecord.id).desc())
        .limit(40)
    ).fetchall()
    return {
        "sources": sources,
        "techs": techs,
        "grades": _GRADES,
        "grade_counts": grade_counts,
        "top_companies": top_companies,
    }


def _pagination_ctx(total: int, page: int, **filters) -> dict:
    total_pages = max(1, math.ceil(total / _PAGE_SIZE))
    return {
        "page": page,
        "total_pages": total_pages,
        "total": total,
        **filters,
    }


@router.get("/signin", response_class=HTMLResponse)
def signin_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "auth/login.html", {})


@router.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    q: str | None = None,
    source: str | None = None,
    tech: str | None = None,
    grade: str | None = None,
    company: str | None = None,
    sal_min: int | None = None,
    sal_max: int | None = None,
    sort: str = "posted-desc",
    page: int = 1,
    include_closed: bool = False,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    import json as _json
    from app.services.analytics import summary_stats, salary_histogram
    jobs = db.execute(
        _query_jobs(q, source, tech, grade, company, sal_min, sal_max, sort, page, include_closed)
    ).scalars().all()
    total = _count_jobs(db, q, source, tech, grade, company, sal_min, sal_max, include_closed)
    sal_hist = salary_histogram(db)
    current_user = get_current_user(request)
    tracked_job_ids: set[int] = set()
    if current_user:
        tracked_job_ids = set(db.execute(
            select(TrackingCard.job_id)
            .where(TrackingCard.user_id == current_user["id"])
            .where(TrackingCard.job_id.isnot(None))
        ).scalars().all())
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            **_common_context(db),
            "jobs": jobs,
            "tech_map": _load_tech_map(db, jobs),
            "stats": summary_stats(db),
            "sal_hist_json": _json.dumps(sal_hist),
            "sort": sort,
            "include_closed": include_closed,
            "current_user": current_user,
            "tracked_job_ids": tracked_job_ids,
            **_pagination_ctx(
                total, page,
                q=q or "", source=source or "", tech=tech or "",
                grade=grade or "", company=company or "",
                sal_min=sal_min or 0, sal_max=sal_max or 0, sort=sort,
                include_closed=include_closed,
            ),
        },
    )


@router.get("/partials/jobs", response_class=HTMLResponse)
def partial_jobs(
    request: Request,
    q: str | None = None,
    source: str | None = None,
    tech: str | None = None,
    grade: str | None = None,
    company: str | None = None,
    sal_min: int | None = None,
    sal_max: int | None = None,
    sort: str = "posted-desc",
    page: int = 1,
    include_closed: bool = False,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    jobs = db.execute(
        _query_jobs(q, source, tech, grade, company, sal_min, sal_max, sort, page, include_closed)
    ).scalars().all()
    total = _count_jobs(db, q, source, tech, grade, company, sal_min, sal_max, include_closed)
    current_user = get_current_user(request)
    tracked_job_ids: set[int] = set()
    if current_user:
        tracked_job_ids = set(db.execute(
            select(TrackingCard.job_id)
            .where(TrackingCard.user_id == current_user["id"])
            .where(TrackingCard.job_id.isnot(None))
        ).scalars().all())
    return templates.TemplateResponse(
        request,
        "partials/jobs_table.html",
        {
            "jobs": jobs,
            "tech_map": _load_tech_map(db, jobs),
            "current_user": current_user,
            "tracked_job_ids": tracked_job_ids,
            **_pagination_ctx(
                total, page,
                q=q or "", source=source or "", tech=tech or "",
                grade=grade or "", company=company or "",
                sal_min=sal_min or 0, sal_max=sal_max or 0, sort=sort,
                include_closed=include_closed,
            ),
        },
    )


@router.get("/technologies", response_class=HTMLResponse)
def technologies_page(
    request: Request,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    import json as _json
    from app.services.analytics import tech_analytics_data
    data = tech_analytics_data(db)
    return templates.TemplateResponse(request, "tech_analytics.html", {
        "data_json": _json.dumps(data, ensure_ascii=False),
        "kpi": data["kpi"],
        "source_counts": data["source_counts"],
        "grade_counts": data["grade_counts"],
    })


@router.get("/companies", response_class=HTMLResponse)
def companies_page(
    request: Request,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    import json as _json
    from collections import defaultdict as _dd

    rows = db.execute(
        select(JobRecord.company, func.count(JobRecord.id).label("cnt"))
        .group_by(JobRecord.company)
        .order_by(func.count(JobRecord.id).desc())
        .limit(120)
    ).fetchall()
    names = [r.company for r in rows]

    grade_rows = db.execute(
        select(JobRecord.company, JobRecord.grade, func.count(JobRecord.id))
        .where(JobRecord.company.in_(names))
        .where(JobRecord.grade.isnot(None))
        .group_by(JobRecord.company, JobRecord.grade)
    ).fetchall()
    grade_mix: dict = _dd(dict)
    for company, grade, cnt in grade_rows:
        grade_mix[company][grade] = cnt

    tech_rows = db.execute(
        select(JobRecord.company, Technology.name, func.count(VacancyTechnology.vacancy_id).label("cnt"))
        .join(VacancyTechnology, VacancyTechnology.vacancy_id == JobRecord.id)
        .join(Technology, Technology.id == VacancyTechnology.tech_id)
        .where(JobRecord.company.in_(names))
        .group_by(JobRecord.company, Technology.name)
    ).fetchall()
    company_tech_raw: dict = _dd(list)
    for company, tech_name, cnt in tech_rows:
        company_tech_raw[company].append({"name": tech_name, "cnt": cnt})
    company_techs = {
        c: sorted(v, key=lambda x: -x["cnt"])[:10]
        for c, v in company_tech_raw.items()
    }

    # Weekly sparkline data (8 weeks)
    now = datetime.now(_tz.utc)
    cutoff = now - timedelta(weeks=8)
    spark_rows = db.execute(
        select(JobRecord.company, JobRecord.created_at)
        .where(JobRecord.company.in_(names))
        .where(JobRecord.created_at >= cutoff)
    ).fetchall()
    weekly_counts: dict = {n: [0] * 8 for n in names}
    for co, created_at in spark_rows:
        dt = created_at if created_at.tzinfo else created_at.replace(tzinfo=_tz.utc)
        wk = int((now - dt).total_seconds() / 604800)
        slot = 7 - min(wk, 7)
        if 0 <= slot < 8:
            weekly_counts[co][slot] += 1

    # Average salary by grade per company
    sal_rows = db.execute(
        select(JobRecord.company, JobRecord.grade, JobRecord.salary_min, JobRecord.salary_max)
        .where(JobRecord.company.in_(names))
        .where(JobRecord.grade.isnot(None))
        .where(JobRecord.salary_min.isnot(None))
        .where(JobRecord.salary_min > 100)
    ).fetchall()
    salary_raw: dict = _dd(lambda: _dd(list))
    for co, grade, sal_min, sal_max in sal_rows:
        avg = (sal_min + sal_max) / 2 if sal_max else sal_min
        salary_raw[co][grade].append(avg)
    salary_by_grade: dict = {
        co: {g: round(sum(vals) / len(vals)) for g, vals in grades.items() if vals}
        for co, grades in salary_raw.items()
    }

    # Recent jobs per company (top 6 by recency, using window function)
    row_num = func.row_number().over(
        partition_by=JobRecord.company,
        order_by=JobRecord.created_at.desc(),
    ).label("rn")
    subq = select(
        JobRecord.id, JobRecord.company, JobRecord.title,
        JobRecord.grade, JobRecord.created_at, row_num,
    ).where(JobRecord.company.in_(names)).subquery()
    recent_rows = db.execute(select(subq).where(subq.c.rn <= 6)).fetchall()
    recent_jobs: dict = _dd(list)
    for row in recent_rows:
        dt_str = row.created_at.isoformat() if row.created_at else None
        recent_jobs[row.company].append({
            "id": row.id,
            "title": row.title,
            "grade": row.grade,
            "created_at": dt_str,
        })

    companies_data = [
        {
            "name": r.company,
            "cnt": r.cnt,
            "rank": i + 1,
            "techs": company_techs.get(r.company, []),
            "grades": grade_mix.get(r.company, {}),
            "weekly": weekly_counts.get(r.company, [0] * 8),
            "salary_by_grade": salary_by_grade.get(r.company, {}),
            "recent": recent_jobs.get(r.company, []),
            "url": f"/companies/{quote(r.company, safe='')}",
        }
        for i, r in enumerate(rows)
    ]
    return templates.TemplateResponse(request, "companies.html", {
        "companies_json": _json.dumps(companies_data, ensure_ascii=False),
        "total": len(rows),
    })


@router.get("/companies/{company_name:path}", response_class=HTMLResponse)
def company_detail(
    request: Request,
    company_name: str,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    jobs = db.execute(
        select(JobRecord)
        .where(JobRecord.company == company_name)
        .order_by(JobRecord.created_at.desc())
    ).scalars().all()
    if not jobs:
        return HTMLResponse("<h2>Company not found</h2>", status_code=404)

    job_ids = [j.id for j in jobs]
    tech_counts = db.execute(
        select(Technology.name, func.count(VacancyTechnology.vacancy_id).label("cnt"))
        .join(VacancyTechnology, VacancyTechnology.tech_id == Technology.id)
        .where(VacancyTechnology.vacancy_id.in_(job_ids))
        .group_by(Technology.name)
        .order_by(func.count(VacancyTechnology.vacancy_id).desc())
    ).fetchall()

    tech_map = _load_tech_map(db, jobs)

    active_count = sum(1 for j in jobs if j.closed_at is None)
    closed_count = len(jobs) - active_count

    return templates.TemplateResponse(request, "company.html", {
        "company_name": company_name,
        "jobs": jobs,
        "tech_counts": tech_counts,
        "tech_map": tech_map,
        "active_count": active_count,
        "closed_count": closed_count,
    })


@router.get("/jobs/{job_id}", response_class=HTMLResponse)
def job_detail(
    request: Request,
    job_id: int,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    job = db.execute(select(JobRecord).where(JobRecord.id == job_id)).scalar_one_or_none()
    if job is None:
        return HTMLResponse("<h2>Vacancy not found</h2>", status_code=404)
    techs = db.execute(
        select(Technology.name)
        .join(VacancyTechnology, VacancyTechnology.tech_id == Technology.id)
        .where(VacancyTechnology.vacancy_id == job_id)
        .order_by(Technology.name)
    ).scalars().all()
    return templates.TemplateResponse(request, "job.html", {"job": job, "techs": techs})


@router.get("/analytics", response_class=HTMLResponse)
def analytics_page(
    request: Request,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    import json as _json
    from app.services.analytics import (
        grade_distribution, source_distribution, summary_stats, tech_cooccurrence,
        source_grade_mix, salary_histogram, salary_by_grade, salary_by_role,
        top_tech_counts, weekly_vacancy_counts, role_category_stats, top_job_titles,
    )
    stats = summary_stats(db)
    data = {
        'stats': stats,
        'source_dist': dict(source_distribution(db)),
        'grade_dist': dict(grade_distribution(db)),
        'src_grade': source_grade_mix(db),
        'cooccurrence': [[t1, t2, cnt, lift] for t1, t2, cnt, lift in tech_cooccurrence(db, limit=60)],
        'tech_counts': top_tech_counts(db, limit=20),
        'salary_hist': salary_histogram(db),
        'salary_by_grade': salary_by_grade(db),
        'salary_by_role': salary_by_role(db),
        'weekly': weekly_vacancy_counts(db, weeks=16),
        'role_categories': role_category_stats(db),
        'top_titles': top_job_titles(db),
    }
    return templates.TemplateResponse(request, "analytics.html", {
        "data_json": _json.dumps(data, ensure_ascii=False),
        "stats": stats,
    })




@router.post("/ingest", response_class=HTMLResponse)
def ingest(
    request: Request,
    keywords: str = Form(default="DevOps"),
) -> HTMLResponse:
    keyword_list = [item.strip() for item in keywords.split(",") if item.strip()]
    stats = run_ingestion(keywords=keyword_list or ["DevOps"])
    return templates.TemplateResponse(request, "partials/ingest_result.html", {"stats": stats})
