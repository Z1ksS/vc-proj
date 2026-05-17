# Job VC

Internal tool for ingesting IT vacancies from Ukrainian job boards, normalizing and deduplicating them, and browsing results in a FastAPI + HTMX UI. Core goal: collect full vacancy descriptions for tech stack analysis.

## Stack
- FastAPI + Jinja2 + HTMX
- SQLAlchemy 2.x + PostgreSQL
- Parsers: Djinni, DOU, work.ua, NoFluffJobs

## Quick Start

```bash
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and fill in `DATABASE_URL` + `ANTHROPIC_API_KEY`.

Run web app:
```bash
uvicorn app.main:app --reload
# http://127.0.0.1:8000
```

## Data Collection

### Ingest (collect vacancies from listing pages)
```bash
# All categories from data/categories.json (~38 categories, all 4 sources)
python -m app.ingest --all-categories

# Specific sources or keywords
python -m app.ingest --all-categories --sources djinni dou
python -m app.ingest --keywords Python DevOps --sources djinni
```

Djinni descriptions are collected automatically during ingest (embedded in listing HTML).

### Enrich (fetch full descriptions from individual vacancy pages)
```bash
# All sources (DOU, work.ua, NoFluffJobs)
python -m app.enrich

# Specific sources
python -m app.enrich --sources dou workua
```

Enrich skips already-enriched records and auto-marks vacancies as closed if their page returns 404.

### Extract (build tech stack index from descriptions)
```bash
# Extract technologies for all new vacancies (incremental)
python -m app.extract

# Re-extract everything (use after updating data/tech_terms.json)
python -m app.extract --reprocess-all
```

Technologies are stored in `technologies` + `vacancy_technologies` tables. Dictionary: `data/tech_terms.json` (~220 terms with aliases).

### Evaluate extraction quality (LLM sampling)
```bash
# 100 with-tech + 50 zero-tech vacancies, mixed sample
python -m app.eval_extract

# Target only zero-tech vacancies with technical-sounding titles
python -m app.eval_extract --zero-only

# Custom sample size + save full results
python -m app.eval_extract --zero-only -n 150 --output results.json
```

Requires `ANTHROPIC_API_KEY` in `.env`. Asks Claude what the regex missed, prints a frequency report of missed terms.

### Enrich meta (salary + grade from vacancy fields)
```bash
# Process all records (idempotent, ~2 sec)
python -m app.enrich_meta

# Only new vacancies where grade IS NULL (after daily ingest)
python -m app.enrich_meta --only-new
```

Parses `salary` field → `salary_min / salary_max / salary_currency` (USD, EUR, UAH, PLN).
Extracts grade from `title` → Junior / Middle / Senior / Lead / Staff / Principal / Intern.

### Typical daily workflow
```bash
python -m app.ingest --all-categories
python -m app.enrich
python -m app.extract
python -m app.enrich_meta --only-new
```

On the production server this is handled by systemd cron jobs (see `/etc/cron.d/job-vc`).

## Categories

`data/categories.json` — 38 canonical IT categories (Python, JavaScript, DevOps, etc.) with per-source keyword mappings. Each source uses its own slugs:
- **DOU / NoFluffJobs** — free-text keywords
- **Djinni** — fixed category slugs (e.g. `ML AI`, `Fullstack`, subcategories like `Angular`, `React.js`)
- **work.ua** — IT-filtered URLs (`/jobs-it-{keyword}/`)

> **Note:** work.ua may return 0 results when run from a server IP due to rate limiting / IP blocking. It works correctly from a local machine. If ingest shows 0 results for all work.ua keywords, the server IP is likely blocked.

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./jobs.db` | DB connection string (PostgreSQL in production) |
| `ENABLE_SOURCES` | `djinni,dou,nofluffjobs,workua` | Active parsers |
| `INGEST_LOG_PATH` | `logs/ingest.log` | Ingest log file |
| `ENRICH_LOG_PATH` | `logs/enrich.log` | Enrich log file |
| `ENRICH_DELAY` | `1.5` | Seconds between enrich requests |
| `CLOSE_AFTER_DAYS` | `3` | Days before unseen vacancy is marked closed |
| `EXTRACT_LOG_PATH` | `logs/extract.log` | Extract log file |
| `ANTHROPIC_API_KEY` | — | API key for Phase 4b eval (`app.eval_extract`) |

## Tests

```bash
pytest -q
```

## UI Pages

| URL | Description |
|-----|-------------|
| `/` | Main vacancies list — filter by keyword, source, grade, tech, company, salary; "Show closed" toggle |
| `/jobs/{id}` | Vacancy detail — title, company, grade, salary, full tech list, description |
| `/companies` | Companies leaderboard (2-column layout) — sparklines, tech bars, drilldown panel, sort + search |
| `/companies/{name}` | Company detail — KPI strip, tech stack, Active / History tabs |
| `/technologies` | Technologies ranked by vacancy count — top 30 bars, by-role breakdown (10 roles), heatmap |
| `/analytics` | Market analytics — 5 KPI cards, weekly trend chart, co-occurrence with lift, **Roles tab** (category bars + top-60 real job titles) |

## Project Phases

- [x] **Phase 1** — Parsers + SQLite ingest + deduplication + lifecycle tracking
- [x] **Phase 2** — `data/categories.json` with 38 IT categories, all-categories ingest
- [x] **Phase 3** — Full description collection (listing-embedded for Djinni, page-fetch enrich for DOU/work.ua/NoFluffJobs)
- [x] **Phase 4a** — Tech stack extraction: regex dictionary (~220 terms), `technologies` + `vacancy_technologies` tables
- [x] **Phase 4b** — LLM evaluation of extraction quality (5 iterations, zero-tech rate 28% → 9%)
- [x] **Phase 4c** — Salary parsing + grade extraction (2,651 graded, 1,318 with salary)
- [x] **Phase 5a** — Enhanced UI: filters, `/technologies`, `/companies` (redesigned), `/companies/{name}` (Active/History tabs), `/jobs/{id}`, dark theme
- [x] **Phase 5b** — Weekly trend chart on analytics; sparklines on companies page; "Show closed" toggle
- [x] **Phase 5c** — Analytics UI: 5-card KPI strip, grade/source charts, weekly trend chart, tech co-occurrence with lift score
- [x] **Phase 6a** — PostgreSQL migration
- [ ] **Phase 6b** — robota.ua parser
- [x] **Phase 7** — Role classification: 10 broad categories + "Top job titles" data-driven view on `/analytics`
