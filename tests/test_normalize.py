from app.services.normalize import (
    build_fingerprint,
    normalize_job,
    normalize_salary,
    normalize_text,
)
from models.job import Job


def test_normalize_caps_varchar_fields_to_column_limit() -> None:
    long = "x" * 1000
    job = Job(
        id="src-1",
        title=long,
        company=long,
        salary=long,
        link="https://example.com/job/1",
        job_format=long,
        description=None,
    )
    result = normalize_job(job, source="djinni")
    assert len(result.title) == 256
    assert len(result.company) == 256
    assert len(result.salary) == 256
    assert len(result.job_format) == 256
    assert len(result.normalized_title) <= 256
    assert len(result.normalized_company) <= 256


def test_normalize_text_collapses_case_punctuation_spaces() -> None:
    value = "  Senior,   PYTHON  Engineer!!! "
    assert normalize_text(value) == "senior python engineer"


def test_normalize_salary_keeps_human_readable_values() -> None:
    value = "  4000\u00a0-\u00a06000   USD "
    assert normalize_salary(value) == "4000 - 6000 USD"


def test_fingerprint_uses_normalized_parts() -> None:
    assert build_fingerprint("python engineer", "acme") == "python engineer::acme"

