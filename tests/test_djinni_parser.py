from types import SimpleNamespace

from parsers.djinni import DjinniParser


_HTML = """
<html><body>
  <div class="job-item">
    <a class="job_item__header-link"
       href="/jobs/826714-senior-data-engineer/?ref=job_search&sid=a262742765814c929b49b905f78b8566">link</a>
    <h2 class="job-item__position">Senior Data Engineer</h2>
    <span class="small text-gray-800">CrunchCode</span>
  </div>
</body></html>
"""


def test_djinni_strips_tracking_params_from_link(monkeypatch):
    """Djinni appends a volatile ?sid= to hrefs; it must be stripped so the
    derived id/link stay stable across runs (otherwise every vacancy re-inserts)."""
    parser = DjinniParser()
    monkeypatch.setattr(parser, "get_last_page_number", lambda base_url: 1)
    monkeypatch.setattr(parser, "_get", lambda url, **kw: SimpleNamespace(text=_HTML))

    jobs = parser.parse("Python")

    assert len(jobs) == 1
    job = jobs[0]
    assert job.link == "https://djinni.co/jobs/826714-senior-data-engineer/"
    assert "sid=" not in job.link
    assert "?" not in job.link
    # id is company::link — must also be free of the volatile param
    assert job.id == "CrunchCode::https://djinni.co/jobs/826714-senior-data-engineer/"
