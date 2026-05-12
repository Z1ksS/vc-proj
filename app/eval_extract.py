"""
Phase 4b — LLM evaluation of regex tech extraction quality.

Samples vacancies, asks Claude what the regex missed, aggregates missed terms.

Usage:
    python -m app.eval_extract                        # 100 with-tech + 50 zero-tech
    python -m app.eval_extract --with-tech 50 --zero-tech 20
    python -m app.eval_extract --zero-only            # 100 zero-tech technical vacancies only
    python -m app.eval_extract --zero-only -n 150     # specify sample size
    python -m app.eval_extract --output results.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter

import anthropic
from sqlalchemy import text

from app.db import engine
from app.services.tech_extract import extract_technologies

_TECHNICAL_TITLE_KEYWORDS = [
    "engineer", "developer", "dev", "qa", "devops", "architect",
    "data", "security", "backend", "frontend", "fullstack", "full stack",
    "senior", "middle", "junior", "lead", "staff", "principal",
    "sre", "platform", "embedded", "android", "ios", "mobile",
    "machine learning", "ml ", " ai ", "scientist",
]

_MODEL = "claude-haiku-4-5-20251001"
_MAX_DESC_CHARS = 2500
_REQUEST_DELAY = 0.3


def _is_technical(title: str) -> bool:
    t = title.lower()
    return any(kw in t for kw in _TECHNICAL_TITLE_KEYWORDS)


def _sample_vacancies(n_with_tech: int, n_zero_tech: int) -> list[dict]:
    with engine.connect() as conn:
        with_tech = conn.execute(text("""
            SELECT j.id, j.title, j.source, j.description
            FROM jobs j
            WHERE j.description IS NOT NULL
              AND j.id IN (SELECT DISTINCT vacancy_id FROM vacancy_technologies)
            ORDER BY RANDOM()
            LIMIT :n
        """), {"n": n_with_tech}).fetchall()

        zero_candidates = conn.execute(text("""
            SELECT j.id, j.title, j.source, j.description
            FROM jobs j
            WHERE j.description IS NOT NULL
              AND j.id NOT IN (SELECT DISTINCT vacancy_id FROM vacancy_technologies)
            ORDER BY RANDOM()
            LIMIT 750
        """)).fetchall()

    zero_tech = [r for r in zero_candidates if _is_technical(r.title)][:n_zero_tech]

    rows = []
    for r in list(with_tech) + zero_tech:
        rows.append({
            "id": r.id,
            "title": r.title,
            "source": r.source,
            "description": (r.description or "")[:_MAX_DESC_CHARS],
            "regex_found": extract_technologies(f"{r.title} {r.description or ''}"),
        })
    return rows


def _sample_zero_only(n: int) -> list[dict]:
    """Sample only zero-tech vacancies with technical-sounding titles."""
    with engine.connect() as conn:
        # Pull all zero-tech vacancies to filter by title
        candidates = conn.execute(text("""
            SELECT j.id, j.title, j.source, j.description
            FROM jobs j
            WHERE j.description IS NOT NULL
              AND j.id NOT IN (SELECT DISTINCT vacancy_id FROM vacancy_technologies)
            ORDER BY RANDOM()
            LIMIT 750
        """)).fetchall()

    technical = [r for r in candidates if _is_technical(r.title)]
    sample = technical[:n]
    print(f"  Technical zero-tech pool: {len(technical)} | sampling {len(sample)}")

    return [
        {
            "id": r.id,
            "title": r.title,
            "source": r.source,
            "description": (r.description or "")[:_MAX_DESC_CHARS],
            "regex_found": extract_technologies(f"{r.title} {r.description or ''}"),
        }
        for r in sample
    ]


def _ask_llm(client: anthropic.Anthropic, vacancy: dict) -> list[str]:
    regex_list = ", ".join(vacancy["regex_found"]) if vacancy["regex_found"] else "nothing"
    prompt = f"""Job title: {vacancy["title"]}

Description:
{vacancy["description"]}

A regex extractor already found these technologies: {regex_list}

List any important technologies, frameworks, tools, or programming languages mentioned in the description that the regex extractor MISSED.
Return ONLY a valid JSON array of strings. If nothing was missed, return [].
Do not include items already in the found list. Do not add explanations."""

    try:
        msg = client.messages.create(
            model=_MODEL,
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        start = raw.find("[")
        end = raw.rfind("]") + 1
        if start == -1 or end == 0:
            return []
        return json.loads(raw[start:end])
    except anthropic.APIStatusError as e:
        print(f"\nAPI error {e.status_code}: {e.message}", file=sys.stderr)
        if e.status_code in (400, 401, 403):
            print("Fatal: stopping.", file=sys.stderr)
            sys.exit(1)
        return []
    except anthropic.APIConnectionError as e:
        print(f"\nConnection error: {e}", file=sys.stderr)
        return []
    except (json.JSONDecodeError, IndexError):
        return []


def run_evaluation(
    n_with_tech: int = 100,
    n_zero_tech: int = 50,
    zero_only: bool = False,
    zero_only_n: int = 100,
    output_path: str | None = None,
) -> dict:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY env var not set", file=sys.stderr)
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    if zero_only:
        vacancies = _sample_zero_only(zero_only_n)
        total = len(vacancies)
        print(f"Zero-only mode: {total} technical zero-tech vacancies")
    else:
        vacancies = _sample_vacancies(n_with_tech, n_zero_tech)
        total = len(vacancies)
        print(f"Sampled {total} vacancies ({n_with_tech} with-tech + {len(vacancies) - n_with_tech} zero-tech)")

    missed_counter: Counter[str] = Counter()
    results = []

    for i, v in enumerate(vacancies):
        missed = _ask_llm(client, v)
        missed_counter.update(t.strip() for t in missed if t.strip())
        results.append({
            "id": v["id"],
            "title": v["title"],
            "source": v["source"],
            "regex_found": v["regex_found"],
            "llm_missed": missed,
        })

        if (i + 1) % 10 == 0:
            print(f"  {i + 1}/{total} done...")

        time.sleep(_REQUEST_DELAY)

    summary = {
        "total_evaluated": total,
        "missed_terms": missed_counter.most_common(),
        "detail": results,
    }

    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        print(f"Full results saved to {output_path}")

    return summary


def _print_report(summary: dict) -> None:
    print(f"\n=== MISSED TERMS (top 40) — evaluated {summary['total_evaluated']} vacancies ===")
    for term, count in summary["missed_terms"][:40]:
        bar = "█" * count
        print(f"  {count:3d}  {term:<35} {bar}")

    zero_regex_with_misses = [
        r for r in summary["detail"]
        if not r["regex_found"] and r["llm_missed"]
    ]
    print(f"\n=== ZERO-TECH VACANCIES where LLM found something: {len(zero_regex_with_misses)} ===")
    for r in zero_regex_with_misses[:15]:
        print(f"  [{r['source']}] {r['title']}")
        print(f"    missed: {r['llm_missed']}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="LLM evaluation of regex tech extraction")
    p.add_argument("--with-tech", type=int, default=100, metavar="N",
                   help="Vacancies with ≥1 tech to sample (default: 100)")
    p.add_argument("--zero-tech", type=int, default=50, metavar="N",
                   help="Zero-tech technical vacancies to sample (default: 50)")
    p.add_argument("--zero-only", action="store_true",
                   help="Sample only from zero-tech vacancies with technical titles")
    p.add_argument("-n", type=int, default=100, metavar="N",
                   help="Sample size for --zero-only mode (default: 100)")
    p.add_argument("--output", default=None, metavar="FILE",
                   help="Save full JSON results to this file")
    return p


def main() -> None:
    args = build_parser().parse_args()
    summary = run_evaluation(
        n_with_tech=args.with_tech,
        n_zero_tech=args.zero_tech,
        zero_only=args.zero_only,
        zero_only_n=args.n,
        output_path=args.output,
    )
    _print_report(summary)


if __name__ == "__main__":
    main()
