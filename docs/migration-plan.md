# Migration Plan — job-vc

**Date:** 2026-05-06 (last updated: 2026-05-17 — role classification done)

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
| Phase 5a — Enhanced UI | **DONE** | Tech/grade/company filters; pagination; /technologies, /companies (redesign), /companies/{name} (Active/History tabs), /jobs/{id}. |
| Phase 5b — Trend analytics | **DONE** | Weekly trend chart on /analytics; sparklines on companies page; "Show closed" toggle on main page. |
| Phase 5c — Analytics UI | **DONE** | /analytics: 5-card KPI strip with sparkline, grade/source dist, weekly chart, co-occurrence with lift column. |
| Phase 6a — PostgreSQL migration | **DONE** | Production DB migrated from SQLite to PostgreSQL. |
| Phase 6b — robota.ua parser | pending | — |
| Phase 7 — Role classification | **DONE** | 10 broad categories + `top_job_titles()` real-title view on /analytics Roles tab. |

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
- Production: replaced APScheduler with systemd cron jobs (`/etc/cron.d/job-vc`); logs to `/var/log/job-vc/cron.log`.

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

### Phase 4c — Salary + Grade Extraction ✅

- `app/services/salary_parse.py` — parses raw `salary` field: `"$3000–5000"`, `"від 1500 до 3000 USD"`, `"3 000 грн"` → `(salary_min, salary_max, salary_currency)`.
- `app/services/grade_extract.py` — regex on title → Junior / Middle / Senior / Lead / Staff / Principal / Intern.
- `app/enrich_meta.py` — batch script; default rewrites all, `--only-new` for incremental after daily ingest.
- **Result:** 2,651 vacancies graded (34%), 1,318 with structured salary (17%). Low salary coverage is expected — most sources don't publish salary. Grade coverage is limited to titles that explicitly mention level (Ukrainian market norm).

---

### Phase 5a — Enhanced UI ✅

- **Main page filters**: grade + technology + company chip + salary range — HTMX partial update, no full reload.
- **"Show closed" toggle**: checkbox in sidebar; `include_closed` bool param on `/` and `/partials/jobs`; closed vacancies shown with strikethrough styling.
- **Pagination**: 50 per page, Prev/Next via HTMX, resets on filter change.
- **`/technologies`** — all technologies ranked by vacancy count; click → filtered vacancies.
- **`/companies`** (redesigned) — 2-column layout: leaderboard on left + sticky drilldown panel on right.
  - Leaderboard: each row has inline SVG sparkline (8-week trend), grade mix pill, tech chip count, salary range.
  - Drilldown panel: big sparkline, tech frequency bars, grade mix bar + legend, salary by grade cards ($Xk format), recent 6 vacancies.
  - Sort pills (Most active / Fewest / A→Z), search, pagination.
  - Auto-selects first company on page load.
- **`/companies/{name}`** (redesigned) — KPI strip (Active now / Total tracked / Closed % / Tech count); tech chip grid (top 30); **Active / History tabs** — client-side filtering via `data-closed` attribute; closed rows at 55% opacity with "Closed" badge.
- **`/jobs/{id}`** — vacancy detail: title, company, grade, salary, full tech list, full description.
- Tech tags in jobs table (up to 5 + "+N more" → vacancy detail page); company name clickable.
- Grade badges with colour coding per level.
- Dark theme (GitHub Dark palette).

---

### Phase 5b — Trend Analytics ✅

- **`weekly_vacancy_counts(db, weeks=16)`** in `app/services/analytics.py` — buckets all vacancies into 16 weekly slots using UTC timestamps.
- **Weekly trend chart** on `/analytics` Market view — SVG line + area fill, interactive dots with tooltips (absolute count + week label).
- **Sparklines** on `/companies` leaderboard rows — 8-week inline SVG per company, area-fill, auto-scaled.
- **Drilldown sparkline** in `/companies` side panel — same data, larger render, zero-state handled.

---

### Phase 5c — Analytics UI ✅

- **`/analytics`** — 5-card KPI strip:
  1. Total vacancies (with 16-week sparkline)
  2. New today
  3. Companies hiring
  4. Median salary (computed client-side from salary histogram)
  5. Disclosure rate (vacancies with salary / total)
- Grade distribution bar chart; source breakdown; weekly trend chart (see Phase 5b).
- **Tech co-occurrence** — top 60 pairs; added **Lift** column (green highlight when ≥3×; formula: `(cnt_ab × total) / (cnt_a × cnt_b)`); sortable by Count or Lift.
- `app/services/analytics.py`:
  - `summary_stats` — added `companies` (distinct count).
  - `tech_cooccurrence` — now returns 4-tuple `(tech1, tech2, cnt, lift)`.
  - `weekly_vacancy_counts` — new function.

---

### Phase 6a — PostgreSQL Migration ✅

- Production DB migrated from SQLite to PostgreSQL.
- `DATABASE_URL` in `.env` updated to `postgresql+psycopg2://...`.
- `psycopg2-binary` added to `requirements.txt`.
- `check_same_thread` SQLite workaround removed.

---

### Phase 7 — Role Classification ✅

**Combo approach implemented** (broad categories + data-driven titles):

- `_ROLES` expanded from 6 → 10: Backend, Frontend, DevOps, Data, QA, Mobile, **Security, PM, Support, Hardware**.
- `_ROLE_MAP` reordered — specific roles first (Security before DevOps to catch "devsecops" correctly), Backend last as catch-all.
- `role_category_stats(db)` — counts vacancies per category + "Other" (unclassified tail).
- `top_job_titles(db, limit=60)` — normalizes titles (strips grade prefix), groups by normalized title, returns top 60 with count + top-5 techs per title.
- `/analytics` **Roles tab**: left panel = category bars with % coverage; right panel = salary boxplots by role; bottom = top-60 real job titles table with progress bars + tech chips.
- `/technologies` "By Role" grid updated to 10 cards; `GRADE_WEIGHTS` extended for new roles; `.role-split` changed to `auto-fill` grid.

---

## Upcoming Phases

### Phase 6b — robota.ua Parser

1. Manual investigation first: DevTools, check for Cloudflare, login walls, JS rendering, XHR pagination.
2. Implement `parsers/robotaua.py` following `BaseParser` interface.
3. Likely: `requests` + BeautifulSoup; XHR endpoint if needed.

**Risk:** anti-bot is the main unknown. Start with polite crawling. Avoid Playwright unless confirmed necessary.

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
| work.ua IP rate limiting on server | **High** | Medium | Server IP gets blocked; runs 0 results in <10s. Workaround: run ingest locally with `DATABASE_URL` pointing to remote DB, or add delays + User-Agent rotation |
| robota.ua blocks scrapers | High | Low (additive) | Start with polite crawling |
| LLM costs in Phase 4 | Low (if regex-first) | Medium | Gate LLM behind recall threshold; regex handles 85%+ |
| Postgres migration loses data | Low | High | Backup `jobs.db` before Phase 6; idempotent migration script |
| APScheduler overlapping runs | Low | Medium | `coalesce=True, max_instances=1` already set |
| DOU enrich backlog latency | Medium | Low | ~2785 pending items × 1.5s = ~82 min per full enrich run; acceptable for nightly batch |
