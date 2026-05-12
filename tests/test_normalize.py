from app.services.normalize import build_fingerprint, normalize_salary, normalize_text


def test_normalize_text_collapses_case_punctuation_spaces() -> None:
    value = "  Senior,   PYTHON  Engineer!!! "
    assert normalize_text(value) == "senior python engineer"


def test_normalize_salary_keeps_human_readable_values() -> None:
    value = "  4000\u00a0-\u00a06000   USD "
    assert normalize_salary(value) == "4000 - 6000 USD"


def test_fingerprint_uses_normalized_parts() -> None:
    assert build_fingerprint("python engineer", "acme") == "python engineer::acme"

