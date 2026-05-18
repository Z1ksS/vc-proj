from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import select
from starlette.middleware.sessions import SessionMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.auth import router as auth_router
from app.db import SessionLocal, engine
from app.ingest import run_ingestion
from app.models import Base, JobRecord
from app.web.routes import router as web_router
from app.web.tracking import router as tracking_router

logger = logging.getLogger("job_vc.scheduler")


class JobOut(BaseModel):
    id: int
    source: str
    title: str
    company: str
    salary: str
    link: str
    job_format: str


class IngestRequest(BaseModel):
    keywords: list[str] = Field(default_factory=lambda: ["DevOps"])
    sources: list[str] | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    from app.scheduler import SCHEDULER_ENABLED, build_scheduler

    scheduler = None
    if SCHEDULER_ENABLED:
        scheduler = build_scheduler()
        scheduler.start()
        job_ids = [j.id for j in scheduler.get_jobs()]
        logger.info("Scheduler started | jobs=%s", job_ids)

    yield

    if scheduler is not None and scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")


def create_app() -> FastAPI:
    app = FastAPI(title="Job VC", version="0.1.0", lifespan=lifespan)
    app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")
    app.add_middleware(
        SessionMiddleware,
        secret_key=os.getenv("SECRET_KEY", "change-me-in-production"),
    )
    Path("uploads/cv").mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
    app.mount("/static", StaticFiles(directory="app/static"), name="static")
    app.include_router(auth_router)
    app.include_router(tracking_router)
    app.include_router(web_router)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/jobs")
    def list_jobs(limit: int = 200) -> list[JobOut]:
        with SessionLocal() as db:
            rows = db.execute(
                select(JobRecord)
                .order_by(JobRecord.created_at.desc(), JobRecord.id.desc())
                .limit(limit)
            ).scalars().all()
        return [
            JobOut(
                id=row.id,
                source=row.source,
                title=row.title,
                company=row.company,
                salary=row.salary,
                link=row.link,
                job_format=row.job_format,
            )
            for row in rows
        ]

    @app.post("/api/ingest")
    def ingest(payload: IngestRequest) -> dict[str, int]:
        return run_ingestion(keywords=payload.keywords, sources=payload.sources)

    return app


app = create_app()
