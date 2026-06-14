import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.ingest import _upsert_jobs
from app.models import Base, JobRecord
from app.services.normalize import NormalizedJob


@pytest.fixture()
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        yield db


def _job(fp: str, company: str = "Acme") -> NormalizedJob:
    return NormalizedJob(
        source="djinni",
        source_job_id=f"djinni:{fp}",
        title="DevOps Engineer",
        company=company,
        salary="",
        link="https://example.com/job",
        job_format="remote",
        normalized_title="devops engineer",
        normalized_company=(company or "").lower(),
        dedupe_fingerprint=fp,
    )


def test_bad_record_does_not_abort_batch(session) -> None:
    # company=None violates the NOT NULL constraint and fails on flush.
    jobs = [_job("a"), _job("b", company=None), _job("c")]

    inserted, updated = _upsert_jobs(session, jobs)

    assert (inserted, updated) == (2, 0)
    saved = session.execute(select(JobRecord.source_job_id)).scalars().all()
    assert set(saved) == {"djinni:a", "djinni:c"}


def test_all_good_records_persist(session) -> None:
    inserted, updated = _upsert_jobs(session, [_job("a"), _job("b")])

    assert (inserted, updated) == (2, 0)
    assert session.execute(select(JobRecord)).scalars().all()
