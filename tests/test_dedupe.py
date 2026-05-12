from app.services.dedupe import dedupe_jobs
from app.services.normalize import NormalizedJob


def _job(fp: str, title: str = "DevOps Engineer", company: str = "Acme") -> NormalizedJob:
    return NormalizedJob(
        source="djinni",
        source_job_id=f"djinni:{fp}",
        title=title,
        company=company,
        salary="",
        link="https://example.com/job",
        job_format="remote",
        normalized_title=title.lower(),
        normalized_company=company.lower(),
        dedupe_fingerprint=fp,
    )


def test_dedupe_exact_fingerprint() -> None:
    jobs = [_job("devops engineer::acme"), _job("devops engineer::acme")]
    deduped = dedupe_jobs(jobs)
    assert len(deduped) == 1


def test_dedupe_keeps_unique_jobs() -> None:
    jobs = [_job("devops engineer::acme"), _job("sre::acme", title="SRE")]
    deduped = dedupe_jobs(jobs)
    assert len(deduped) == 2

