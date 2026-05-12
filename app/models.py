from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class JobRecord(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_job_id: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    company: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    salary: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    link: Mapped[str] = mapped_column(Text, nullable=False)
    job_format: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    normalized_title: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    normalized_company: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    dedupe_fingerprint: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Lifecycle fields — added in migration 0002
    first_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    # Content fields — added in migration 0002
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    grade: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    salary_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_currency: Mapped[str | None] = mapped_column(String(8), nullable=True)

    # Cross-platform dedup — added in migration 0002; initially = source_job_id
    canonical_vacancy_id: Mapped[str | None] = mapped_column(
        String(512), nullable=True, index=True
    )

    __table_args__ = (Index("ix_jobs_dedupe_source", "dedupe_fingerprint", "source"),)


class Technology(Base):
    __tablename__ = "technologies"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)


class VacancyTechnology(Base):
    __tablename__ = "vacancy_technologies"

    vacancy_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), primary_key=True)
    tech_id: Mapped[int] = mapped_column(ForeignKey("technologies.id"), primary_key=True)
