# Migration Plan — job-vc

**Date:** 2026-05-06 (last updated: 2026-05-12)

---

## Status

| Phase | Status | Notes |
|-------|--------|-------|
| Phase 1 — Parsers + ingest + lifecycle | **DONE** | DOU XHR fix, Alembic + 9 lifecycle columns, APScheduler 2×/day, all 4 sources stable. |
| Phase 2 — 38-category ingest | **DONE** | `data/categories.json`, `--all-categories` CLI flag, per-source keyword mappings, IT filter on work.ua. |
| Phase 3 — Full description collection | **DONE** | Djinni inline from listing HTML; DOU/work.ua/NoFluffJobs via `app/enrich.py`. 7,826 records enriched. |
| Phase 4a — Regex extraction | **DONE** | `data/tech_terms.json` ~220 terms, `technologies` + `vacancy_technologies` tables, `app/extract.py` batch script. |
| Phase 4b — LLM evaluation | **DONE** | 5 iterations via `app/eval_extract.py`, zero-tech rate 28% → 9%, 58,492 tech mentions across 7,824 vacancies. |
| Phase 4c — Salary + grade | **DONE** | `app/enrich_meta.py`: salary_min/max/currency + grade from title. 2,651 graded (34%), 1,318 with salary (17%). |
| Phase 5a — Enhanced UI | **DONE** | Tech/grade/company filters on main page; /technologies and /companies pages. |
| Phase 5c — Analytics UI | **DONE** | /analytics (grade/source dist, tech co-occurrence), /roles (tech stack by role). |
| Phase 5b — Trend analytics | pending | requires ≥1 month of data |
| Phase 6 — PostgreSQL + robota.ua | pending | revisit when SQLite shows real bottlenecks |

---

## Completed Phases

### Phase 1 — Parsers + Ingest + Lifecycle ✅

**Sub-phases delivered:**

**Phase 0 (parser stabilization):**
- DOU: Playwright removed, XHR endpoint `/vacancies/xhr-load/` used instead. Result: 0 → 177 vacancies.
- `playwright` removed from `requirements.txt`.

**Phase 1 (Alembic + lifecycle fields):**
- `alembic/` initialised; `env.py` wired to `DATABASE_URL` + `Base.metadata`; `render_as_batch=True` for SQLite.
- `0001_baseline.py` — empty stamp of existing schema.
- `0002_add_lifecycle_fields.py` — 9 new columns + 5 indices; backfills `first_seen_at = last_seen_at = created_at`, `canonical_vacancy_id = source_job_id`.
- `app/ingest.py`: INSERT/UPDATE lifecycle tracking, `_mark_closed()`, `CLOSE_AFTER_DAYS` env var, all 4 parsers via `_PARSER_REGISTRY`.
- `models/job.py` — added `description: str | None = None`.

**Phase 1.5 (APScheduler):**
- `app/scheduler.py` — 2×/day cron (08:00 + 20:00 UTC), `coalesce=True, max_instances=1`.
- `app/main.py` — `@asynccontextmanager lifespan`; scheduler starts on startup.
- `SCHEDULER_ENABLED`, `SCHEDULE_HOURS` env vars.

---

### Phase 2 — 38-Category Ingest ✅

- `data/categories.json` — 38 canonical IT categories with per-source keyword mappings.
- `--all-categories` flag on `python -m app.ingest`.
- work.ua: IT filter added (`/jobs-it-{keyword}/`), URL encoding for special chars (`c++` → `c%2B%2B`).
- Djinni: correct slugs (e.g. `Fullstack`, not `Full Stack`; `ML AI`, not `AI/ML`).
- Page cap: `_MAX_PAGES = 50` on all parsers to prevent runaway pagination.

---

### Phase 3 — Full Description Collection ✅

- **Djinni**: descriptions extracted inline from listing HTML (`span.js-original-text` — CSS-hidden but present). No extra requests.
- **DOU / work.ua / NoFluffJobs**: `app/enrich.py` batch script fetches individual vacancy pages.
  - CSS selectors: `div.vacancy-section`, `div#job-description`, `article`.
  - `_GONE` sentinel distinguishes deleted/hidden vacancy (404 or selector not found) from network error.
  - Deleted vacancies: `closed_at = now()` instead of erroring.
  - Commits every 50 records; skips already-enriched and already-closed rows.
- **Result**: 7,826 records with `description` populated.

---

---

### Phase 4a — Regex Tech Extraction ✅

- `data/tech_terms.json` — 220+ canonical terms with aliases (e.g. `{"canonical": "PostgreSQL", "aliases": ["postgres", "postgresql", "psql"]}`).
- `app/services/tech_extract.py` — case-insensitive regex scan with custom word boundaries (`(?<![a-zA-Z0-9_\-])`) to handle terms like C++, .NET, C#.
- `alembic/versions/0003_add_tech_tables.py` — `technologies(id, name)` + `vacancy_technologies(vacancy_id, tech_id)` tables.
- `app/extract.py` — batch backfill script; incremental by default, `--reprocess-all` flag to rebuild from scratch.
- **Result:** 58,492 tech mentions across 7,824 vacancies.

---

### Phase 4b — LLM Evaluation ✅

- `app/eval_extract.py` — samples vacancies, asks Claude what regex missed, aggregates missed terms.
- `--zero-only` mode targets vacancies with zero tech found but technical-sounding titles.
- 5 iterative improvement rounds:

| Iteration | tech mentions | zero_techs |
|-----------|--------------|------------|
| #1 baseline | 36,342 | 2,205 (28%) |
| #2 +Node.js, HTML, CSS, React… | 48,623 | 1,085 (14%) |
| #3 +Android, iOS, S3, Redis… | 54,220 | 842 (11%) |
| #4 +DevOps, VLAN, Zendesk… | 58,363 | 750 (10%) |
| #5 +Unity, OSINT, Embedded aliases… | 58,492 | 735 (9%) |

- Remaining 9% (735 vacancies): non-technical roles with tech keywords in title + Ukrainian-language descriptions — accepted as natural floor.

---

---

### Phase 4c — Salary + Grade Extraction ✅

- `app/services/salary_parse.py` — parses raw `salary` field: `"$3000–5000"`, `"від 1500 до 3000 USD"`, `"3 000 грн"` → `(salary_min, salary_max, salary_currency)`.
- `app/services/grade_extract.py` — regex on title → Junior / Middle / Senior / Lead / Staff / Principal / Intern.
- `app/enrich_meta.py` — batch script; default rewrites all, `--only-new` for incremental after daily ingest.
- **Result:** 2,651 vacancies graded (34%), 1,318 with structured salary (17%). Low salary coverage is expected — most sources don't publish salary. Grade coverage is limited to titles that explicitly mention level (Ukrainian market norm).

---

---

### Phase 5a — Enhanced UI ✅

- **Main page filters**: grade + technology + company chip — HTMX partial update, no full reload.
- **Pagination**: 50 per page, Prev/Next via HTMX, resets on filter change.
- **`/technologies`** — all technologies ranked by vacancy count; click → filtered vacancies.
- **`/companies`** — top 150 companies by vacancy count; click → company detail page.
- **`/companies/{name}`** — company detail: full tech stack as clickable cards (with per-vacancy counts) + table of all company vacancies.
- **`/jobs/{id}`** — vacancy detail: title, company, grade, salary, full tech list, full description.
- Tech tags in jobs table (up to 5 + "+N more" → vacancy detail page); company name clickable.
- Grade badges with colour coding per level.
- Dark theme (GitHub Dark palette).

---

### Phase 5c — Analytics UI ✅

- **`/analytics`** — dashboard with 4 summary stat cards (total vacancies, with tech, graded, with salary); grade distribution bar chart; source breakdown; top-40 tech co-occurrence pairs (technologies that appear most often together in the same vacancy).
- **`/roles`** — normalized job roles ranked by vacancy count (grade prefix stripped from titles); top-5 technologies per role with frequency count badge.
- `app/services/analytics.py` — query functions: `summary_stats`, `grade_distribution`, `source_distribution`, `tech_cooccurrence` (self-join on `vacancy_technologies`), `role_tech_stats` (Python-side title normalization + batched tech aggregation).
- Nav updated: Roles + Analytics links added.

---

## Upcoming Phases

### Phase 5b — Trend Analytics

**Prerequisite:** ≥1 month of data accumulated via APScheduler.

**Goal:** trend queries, dashboards.

1. `app/services/analytics.py`:
   - `tech_trends(days=30)` — new vacancies per tech per day (by `first_seen_at`).
   - `rising_technologies(window=7)` — 7-day moving average vs prior 7-day (delta + % change).
   - `falling_technologies(window=7)` — same, descending.
   - `closed_vacancies_report(days=30)` — breakdown by tech/grade/source.
   - `cooccurrence_matrix(min_count=5)` — tech pairs in the same vacancy.
   - `salary_distribution(tech, grade, city)` — min/p25/median/p75/max.
   - `vacancy_lifecycle(source)` — median days `first_seen_at` → `closed_at`.
2. Expose as `/api/analytics/*` endpoints.
3. Metabase (or similar) connected to the same DB:
   - Top 20 technologies (rolling 30 days).
   - Rising vs declining (7-day delta, smoothed).
   - "What closed this week" — proxy for real demand.
   - Salary ranges by grade × city.
   - Co-occurrence heatmap.

**Risk:** Low. All read-only queries. Needs accumulated data — running Phase 5 on <2 weeks of data produces noise.

---

### Phase 6 — PostgreSQL Migration + robota.ua Parser

**Trigger for PostgreSQL:** only if SQLite shows a real bottleneck (slow queries, write conflicts, DB size).  
Before starting: check current DB size/row count, observed slow queries, scheduler + web server conflicts.

**PostgreSQL steps (when triggered):**
1. Update `docker-compose.yml`: add `postgres:16` service, named volume, `DATABASE_URL=postgresql+psycopg2://...`.
2. Run `alembic upgrade head` against fresh Postgres.
3. Remove `check_same_thread` SQLite workaround from `app/db.py`.
4. One-time data migration: dump SQLite → import to Postgres.
5. `requirements.txt`: add `psycopg2-binary`.

**robota.ua steps:**
1. Manual investigation first: DevTools, check for Cloudflare, login walls, JS rendering, XHR pagination (same approach as DOU's `/xhr-load/`).
2. Implement `parsers/robotaua.py` following `BaseParser` interface.
3. Likely: `requests` + BeautifulSoup; XHR endpoint if needed.

**Risk (Postgres):** Medium. SQLite→Postgres type differences must be verified in migrations.  
**Risk (robota.ua):** anti-bot is the main unknown. Start with polite crawling. Avoid Playwright unless confirmed necessary.

---

## Architecture Notes

### What stays as-is
| Component | Why |
|-----------|-----|
| `parsers/base.py` — BaseParser | Clean abstract interface, retry logic. Zero changes needed. |
| `app/services/normalize.py` | Correct, well-tested. Reuse for title/company normalization. |
| `app/services/dedupe.py` | Fuzzy-dedup logic is sound. Within-run dedup; cross-platform dedup is additive. |
| `app/web/routes.py` + templates | UI works. Extend for analytics, don't rewrite. |

### Deferred decisions
- **`httpx` vs `requests`**: requests + retry works. Switch only if async ingestion becomes necessary.
- **SQLModel vs SQLAlchemy**: stay with SQLAlchemy. SQLModel/Alembic friction isn't worth it.
- **LinkedIn scraping**: ToS + aggressive anti-bot. Skip until explicitly scoped.
- **Full async rewrite**: no current bottleneck. APScheduler handles sync jobs.
- **ML-based tech extraction**: regex dict is faster to build, easier to audit, good enough. Start there.

---

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| DOU XHR endpoint changes | Medium | Medium | No contract on private API; add smoke test asserting >0 results per run |
| NoFluffJobs API changes | Medium | Low | Monitor response shape; not documented |
| robota.ua blocks scrapers | High | Low (additive) | Start with polite crawling |
| LLM costs in Phase 4 | Low (if regex-first) | Medium | Gate LLM behind recall threshold; regex handles 85%+ |
| Postgres migration loses data | Low | High | Backup `jobs.db` before Phase 6; idempotent migration script |
| APScheduler overlapping runs | Low | Medium | `coalesce=True, max_instances=1` already set |
