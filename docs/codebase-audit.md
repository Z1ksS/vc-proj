# Codebase Audit — job-vc

**Date:** 2026-05-06  
**Purpose:** Starting-point snapshot before architecture migration.

---

## 1. Directory Structure

```
job-vc/
├── app/                          # FastAPI web application
│   ├── main.py                   # App factory, API routes (/api/health, /api/jobs, /api/ingest)
│   ├── db.py                     # SQLAlchemy engine + session factory
│   ├── ingest.py                 # Ingestion orchestrator (CLI + library function)
│   ├── models.py                 # ORM model: JobRecord
│   ├── web/
│   │   └── routes.py             # Jinja2 web routes (index, search, ingest form)
│   ├── services/
│   │   ├── normalize.py          # Text normalization, fingerprint generation
│   │   └── dedupe.py             # Fuzzy deduplication (rapidfuzz, 95% threshold)
│   ├── static/style.css
│   └── templates/                # Jinja2: base.html, index.html, partials/
├── parsers/
│   ├── base.py                   # BaseParser abstract class (requests + retry)
│   ├── djinni.py                 # djinni.co — requests + BeautifulSoup
│   ├── dou.py                    # jobs.dou.ua — Playwright + BeautifulSoup
│   ├── nofluffjobs.py            # nofluffjobs.com — requests + JSON API
│   ├── workua.py                 # work.ua — requests + BeautifulSoup
│   └── robotaua.py               # EMPTY STUB — robota.ua not implemented
├── models/
│   └── job.py                    # Job dataclass (shared between parsers and app)
├── storage/                      # Storage abstraction — EXISTS BUT UNUSED
│   ├── db.py
│   └── inmemory.py
├── tests/
│   ├── conftest.py
│   ├── test_normalize.py         # 3 tests
│   └── test_dedupe.py            # 2 tests
├── logs/ingest.log               # Ingestion activity log
├── jobs.db                       # SQLite database (production data)
├── jobs_output.txt               # Sample output dump
├── docker-compose.yml
├── Dockerfile.playwright
├── requirements.txt
├── run.py                        # CLI entrypoint → app.ingest:main()
├── README.md
└── DEPLOY.md
```

---

## 2. Parsers

### Common Interface

All parsers inherit `BaseParser` (`parsers/base.py`):
- Shared `requests.Session` with retry logic: 3 attempts, 0.4s exponential backoff, status codes 429/5xx.
- Timeout: 15 seconds.
- Methods: `_get()`, `_post()` — return `requests.Response | None` with silent exception handling.
- Abstract method: `parse(keyword: str) -> List[Job]`

### Parser Summary

| Parser | Platform | Transport | Parsing | Pagination | JS Rendering | Status |
|--------|----------|-----------|---------|------------|--------------|--------|
| `djinni.py` | djinni.co | requests | BeautifulSoup/lxml | Auto-detects last page | No | Active |
| `workua.py` | work.ua | requests | BeautifulSoup/lxml | Auto-detects last page | No | Active |
| `nofluffjobs.py` | nofluffjobs.com | requests POST | JSON (private API) | Single call (pageSize=60) | No | Active |
| `dou.py` | jobs.dou.ua | Playwright | BeautifulSoup/lxml | Scroll-click "more" button | Yes (Chromium) | Active but returning 0 results in recent runs |
| `robotaua.py` | robota.ua | — | — | — | — | **Not implemented** |

### DOU Parser Notes
- Playwright loads page, waits for "domcontentloaded", then polls for a "load more" button every 1.2s until vacancy count stabilizes.
- Gracefully disabled if `playwright` import fails.
- Logs show 0 results in latest runs — likely a CSS selector drift (`.vt`, `.company`, `.salary`, `.cities`).

### NoFluffJobs Notes
- Uses a private undocumented `infiniteSearch+json` API endpoint.
- Hardcoded region `UA` / language `uk`.
- Client-side dedup within a single parse run (normalized title+company set).

---

## 3. Data Model

### Job Dataclass (`models/job.py`)
```python
@dataclass
class Job:
    id: str          # "{company}::{link}" composite
    title: str
    company: str
    salary: str      # raw string, "Not specified" if absent
    link: str
    job_format: str  # remote/office/hybrid + location, parser-specific
```

### ORM Model (`app/models.py`) — Table: `jobs`

| Column | Type | Notes |
|--------|------|-------|
| id | Integer PK | autoincrement |
| source | String(64) | NOT NULL, indexed |
| source_job_id | String(512) | UNIQUE — parser-provided composite ID |
| title | String(256) | NOT NULL, indexed |
| company | String(256) | NOT NULL, indexed |
| salary | String(256) | default="" |
| link | Text | NOT NULL |
| job_format | String(256) | default="" |
| normalized_title | String(256) | NOT NULL, indexed |
| normalized_company | String(256) | NOT NULL, indexed |
| dedupe_fingerprint | String(512) | NOT NULL, indexed |
| created_at | DateTime(tz) | server_default=now() |
| updated_at | DateTime(tz) | server_default=now(), onupdate=now() |

**Composite index:** `(dedupe_fingerprint, source)`

**Upsert logic:** checks `source_job_id`; updates all fields if exists, inserts otherwise. Returns `(inserted, updated)` counts.

### Notable Absences
- No `first_seen_at` / `last_seen_at` / `closed_at` fields — vacancy lifecycle tracking not implemented.
- No technology/skill entity — technologies are not extracted from descriptions.
- No grade/seniority field.
- No `description` field — full text is not stored.
- No `canonical_vacancy_id` for cross-platform deduplication.
- No company/location normalization tables.

---

## 4. Services

### `app/services/normalize.py`
- `normalize_text(text)` — NFKC normalization, lowercase, punctuation removal, whitespace collapse.
- `normalize_salary(salary)` — NBSP → space conversion, strip.
- `make_fingerprint(title, company)` — `"{norm_title}::{norm_company}"` composite key.

### `app/services/dedupe.py`
- `dedupe_jobs(jobs)` — two-tier deduplication:
  1. Exact fingerprint match (dict lookup).
  2. Fuzzy title+company match via `rapidfuzz.fuzz.token_set_ratio`, threshold 95%.
- Returns deduplicated `List[Job]`.

---

## 5. Storage

### Current: SQLite
- `jobs.db` at repo root (or path from `DATABASE_URL` env var).
- No migration system — schema created via `Base.metadata.create_all()` on startup.
- `check_same_thread=False` for SQLite (single-threaded use).

### Unused: `storage/` directory
- Contains `db.py` and `inmemory.py` — likely an earlier abstraction attempt.
- Not imported anywhere in current code.

---

## 6. Ingestion Pipeline

Entry points: CLI (`python run.py`), web form (`POST /ingest`), REST API (`POST /api/ingest`).

**Pipeline steps:**
1. `run_ingestion(keywords, sources)` resolves enabled sources from `ENABLE_SOURCES` env var.
2. For each (source, keyword): instantiates parser, calls `parse(keyword)` → `List[Job]`.
3. Normalizes titles/companies; builds fingerprints.
4. Deduplicates via `dedupe_jobs()`.
5. Upserts into `jobs` table.
6. Returns stats dict: `{raw_jobs, normalized_jobs, deduped_jobs, inserted, updated}`.

**All synchronous** — no async/await, no background workers.

---

## 7. Scheduling

**None implemented.** Ingestion is manual only.

---

## 8. Logging

- Logger: `job_vc.ingest`, level INFO.
- Output: file only (`logs/ingest.log`), no console propagation.
- Format: `%(asctime)s | %(levelname)s | %(name)s | %(message)s`
- Parser exceptions: caught, logged, return empty list.

---

## 9. Web UI

- Framework: FastAPI + Jinja2 + HTMX 1.9.12 (CDN).
- Routes:
  - `GET /` — index with search (ILIKE on title/company) and source filter.
  - `POST /ingest` — runs ingestion, returns HTMX partial.
  - `GET /partials/jobs` — jobs table partial.
  - `GET /api/health`, `GET /api/jobs`, `POST /api/ingest` — REST API.
- Mobile: columns Salary and Format hidden below 740px.

---

## 10. Testing

**5 tests total, all in services layer:**

| File | Tests | What's covered |
|------|-------|----------------|
| `test_normalize.py` | 3 | `normalize_text`, `normalize_salary`, `make_fingerprint` |
| `test_dedupe.py` | 2 | exact dedup, keeps unique |

**Not covered:** parsers, web routes, ingestion pipeline, ORM models, database interactions.

---

## 11. Configuration

| Variable | Default | Purpose |
|----------|---------|---------|
| `DATABASE_URL` | `sqlite:///./jobs.db` | SQLAlchemy connection string |
| `ENABLE_SOURCES` | `dou` | Comma-separated list of active parsers |
| `INGEST_LOG_PATH` | `logs/ingest.log` | Log file path |

No `.env` file in repo (gitignored). No config schema/validation.

**Hardcoded values:**
- Default keywords: `["DevOps"]`
- Retry attempts: 3, backoff: 0.4s
- DOU browser timeout: 30s, scroll delay: 1.2s
- Fuzzy threshold: 95%

---

## 12. Docker

- `docker-compose.yml`: single `app` service, SQLite volume-mounted, `ENABLE_SOURCES=dou`.
- `Dockerfile.playwright`: based on `mcr.microsoft.com/playwright/python:v1.50.0-noble`, installs Chromium.
- No separate DB container, no Postgres, no separate scheduler container.

---

## 13. Key Findings

### What works well
- Clean parser abstraction: `BaseParser` enforces a single contract, retry logic is centralized.
- Two-tier deduplication (exact + fuzzy) is a solid foundation.
- Text normalization service is correct and well-tested.
- Logging infrastructure is in place.
- Docker image for Playwright-dependent DOU parser is ready.

### Gaps relative to target architecture
- **Database:** SQLite, no migrations, no lifecycle fields (`first_seen_at`, `last_seen_at`, `closed_at`), no description storage, no technology entities.
- **Platform coverage:** robota.ua not implemented; DOU parser returning 0 results (selector drift).
- **Scheduling:** Nothing — manual ingestion only.
- **Enrichment:** No technology extraction (regex/LLM), no grade/seniority parsing, no salary normalization to numeric.
- **Analytics:** No trend queries, no co-occurrence, no time-series aggregations.
- **Cross-platform dedup:** No `canonical_vacancy_id`, dedup only works within a single run.
- **Observability:** No console logging, no metrics, no alerting on parse failures.
- **Tests:** 0% coverage on parsers, pipeline, and web layer.
