from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime
from datetime import timezone as _tz
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.ingest import run_ingestion
from app.models import JobRecord, Technology, VacancyTechnology


router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
templates.env.filters["urlquote"] = lambda s: quote(str(s), safe="")


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
    sal_min=None, sal_max=None,
) -> Select:
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(JobRecord.title.ilike(like) | JobRecord.company.ilike(like))
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
    sal_min=None, sal_max=None, sort="posted-desc", page=1,
) -> Select:
    order = _SORT_MAP.get(sort, _SORT_MAP["posted-desc"])
    stmt = select(JobRecord).order_by(*order)
    stmt = _apply_filters(stmt, keyword, source, tech, grade, company, sal_min, sal_max)
    return stmt.offset((page - 1) * _PAGE_SIZE).limit(_PAGE_SIZE)


def _count_jobs(
    db: Session,
    keyword=None, source=None, tech=None, grade=None, company=None,
    sal_min=None, sal_max=None,
) -> int:
    stmt = select(func.count(JobRecord.id))
    stmt = _apply_filters(stmt, keyword, source, tech, grade, company, sal_min, sal_max)
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
    db: Session = Depends(get_db),
) -> HTMLResponse:
    import json as _json
    from app.services.analytics import summary_stats, salary_histogram
    jobs = db.execute(
        _query_jobs(q, source, tech, grade, company, sal_min, sal_max, sort, page)
    ).scalars().all()
    total = _count_jobs(db, q, source, tech, grade, company, sal_min, sal_max)
    sal_hist = salary_histogram(db)
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
            **_pagination_ctx(
                total, page,
                q=q or "", source=source or "", tech=tech or "",
                grade=grade or "", company=company or "",
                sal_min=sal_min or 0, sal_max=sal_max or 0, sort=sort,
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
    db: Session = Depends(get_db),
) -> HTMLResponse:
    jobs = db.execute(
        _query_jobs(q, source, tech, grade, company, sal_min, sal_max, sort, page)
    ).scalars().all()
    total = _count_jobs(db, q, source, tech, grade, company, sal_min, sal_max)
    return templates.TemplateResponse(
        request,
        "partials/jobs_table.html",
        {
            "jobs": jobs,
            "tech_map": _load_tech_map(db, jobs),
            **_pagination_ctx(
                total, page,
                q=q or "", source=source or "", tech=tech or "",
                grade=grade or "", company=company or "",
                sal_min=sal_min or 0, sal_max=sal_max or 0, sort=sort,
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
        company_tech_raw[company].append((tech_name, cnt))
    company_techs = {
        c: [t for t, _ in sorted(v, key=lambda x: -x[1])[:6]]
        for c, v in company_tech_raw.items()
    }

    companies_data = [
        {
            "name": r.company,
            "cnt": r.cnt,
            "rank": i + 1,
            "techs": company_techs.get(r.company, []),
            "grades": grade_mix.get(r.company, {}),
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

    return templates.TemplateResponse(request, "company.html", {
        "company_name": company_name,
        "jobs": jobs,
        "tech_counts": tech_counts,
        "tech_map": tech_map,
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
        source_grade_mix, salary_histogram, salary_by_grade, salary_by_role, top_tech_counts,
    )
    stats = summary_stats(db)
    data = {
        'stats': stats,
        'source_dist': dict(source_distribution(db)),
        'grade_dist': dict(grade_distribution(db)),
        'src_grade': source_grade_mix(db),
        'cooccurrence': [[t1, t2, cnt] for t1, t2, cnt in tech_cooccurrence(db, limit=60)],
        'tech_counts': top_tech_counts(db, limit=20),
        'salary_hist': salary_histogram(db),
        'salary_by_grade': salary_by_grade(db),
        'salary_by_role': salary_by_role(db),
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
