from __future__ import annotations

import math
from collections import defaultdict
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

_GRADES = ["Junior", "Middle", "Senior", "Lead", "Staff", "Principal", "Intern"]
_PAGE_SIZE = 50


def _apply_filters(stmt: Select, keyword, source, tech, grade, company) -> Select:
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
    return stmt


def _query_jobs(keyword=None, source=None, tech=None, grade=None, company=None, page=1) -> Select:
    stmt = select(JobRecord).order_by(JobRecord.created_at.desc(), JobRecord.id.desc())
    stmt = _apply_filters(stmt, keyword, source, tech, grade, company)
    return stmt.offset((page - 1) * _PAGE_SIZE).limit(_PAGE_SIZE)


def _count_jobs(db: Session, keyword=None, source=None, tech=None, grade=None, company=None) -> int:
    stmt = select(func.count(JobRecord.id))
    stmt = _apply_filters(stmt, keyword, source, tech, grade, company)
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
        select(JobRecord.source).distinct().order_by(JobRecord.source)
    ).scalars().all()
    techs = db.execute(
        select(Technology.name)
        .join(VacancyTechnology, VacancyTechnology.tech_id == Technology.id)
        .group_by(Technology.name)
        .order_by(Technology.name)
    ).scalars().all()
    return {"sources": sources, "techs": techs, "grades": _GRADES}


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
    page: int = 1,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    from app.services.analytics import summary_stats
    jobs = db.execute(_query_jobs(q, source, tech, grade, company, page)).scalars().all()
    total = _count_jobs(db, q, source, tech, grade, company)
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            **_common_context(db),
            "jobs": jobs,
            "tech_map": _load_tech_map(db, jobs),
            "stats": summary_stats(db),
            **_pagination_ctx(total, page, q=q or "", source=source or "",
                              tech=tech or "", grade=grade or "", company=company or ""),
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
    page: int = 1,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    jobs = db.execute(_query_jobs(q, source, tech, grade, company, page)).scalars().all()
    total = _count_jobs(db, q, source, tech, grade, company)
    return templates.TemplateResponse(
        request,
        "partials/jobs_table.html",
        {
            "jobs": jobs,
            "tech_map": _load_tech_map(db, jobs),
            **_pagination_ctx(total, page, q=q or "", source=source or "",
                              tech=tech or "", grade=grade or "", company=company or ""),
        },
    )


@router.get("/technologies", response_class=HTMLResponse)
def technologies_page(
    request: Request,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    rows = db.execute(
        select(Technology.name, func.count(VacancyTechnology.vacancy_id).label("cnt"))
        .join(VacancyTechnology, VacancyTechnology.tech_id == Technology.id)
        .group_by(Technology.name)
        .order_by(func.count(VacancyTechnology.vacancy_id).desc())
    ).fetchall()
    return templates.TemplateResponse(request, "technologies.html", {"techs": rows})


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


@router.get("/roles", response_class=HTMLResponse)
def roles_page(
    request: Request,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    from app.services.analytics import role_tech_stats
    roles = role_tech_stats(db)
    return templates.TemplateResponse(request, "roles.html", {"roles": roles})


@router.get("/tech-analytics", response_class=HTMLResponse)
def tech_analytics_page(
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


@router.post("/ingest", response_class=HTMLResponse)
def ingest(
    request: Request,
    keywords: str = Form(default="DevOps"),
) -> HTMLResponse:
    keyword_list = [item.strip() for item in keywords.split(",") if item.strip()]
    stats = run_ingestion(keywords=keyword_list or ["DevOps"])
    return templates.TemplateResponse(request, "partials/ingest_result.html", {"stats": stats})
