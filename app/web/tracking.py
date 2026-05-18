from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.db import get_db
from app.models import JobRecord, TrackingCard, TrackingColumn

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
templates.env.globals["current_user_fn"] = get_current_user

UPLOADS_DIR = Path("uploads/cv")


def _require_user(request: Request) -> dict:
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def _col_to_dict(col: TrackingColumn) -> dict:
    return {"id": str(col.id), "name": col.name, "color": col.color, "position": col.position}


def _card_to_dict(card: TrackingCard) -> dict:
    stack = json.loads(card.stack_json) if card.stack_json else []
    events = json.loads(card.events_json) if card.events_json else []
    cv = (
        {"filename": card.cv_filename, "url": f"/api/tracking/cards/{card.id}/cv"}
        if card.cv_filename else None
    )
    return {
        "id": str(card.id),
        "columnId": str(card.column_id),
        "jobId": card.job_id,
        "title": card.title,
        "company": card.company or "",
        "source": card.source or "",
        "url": card.url or "",
        "stack": stack,
        "salaryMin": card.salary_min,
        "salaryMax": card.salary_max,
        "salaryCurrency": card.salary_currency or "USD",
        "appliedAt": int(card.applied_at.timestamp() * 1000) if card.applied_at else None,
        "notes": card.notes or "",
        "coverLetter": card.cover_letter or "",
        "grade": card.grade or "",
        "location": card.location or "",
        "events": events,
        "cv": cv,
        "createdAt": int(card.created_at.timestamp() * 1000) if card.created_at else None,
    }


# ── Pages ────────────────────────────────────────────────────────────────────

@router.get("/tracking", response_class=HTMLResponse)
def board_page(request: Request) -> HTMLResponse:
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/auth/login")
    return templates.TemplateResponse(request, "board.html", {"current_user": user})


# ── Board state ───────────────────────────────────────────────────────────────

@router.get("/api/tracking/board")
def get_board(request: Request, db: Session = Depends(get_db)) -> dict:
    user = _require_user(request)
    cols = db.execute(
        select(TrackingColumn)
        .where(TrackingColumn.user_id == user["id"])
        .order_by(TrackingColumn.position)
    ).scalars().all()
    cards = db.execute(
        select(TrackingCard)
        .where(TrackingCard.user_id == user["id"])
        .order_by(TrackingCard.id)
    ).scalars().all()
    return {"columns": [_col_to_dict(c) for c in cols], "cards": [_card_to_dict(c) for c in cards]}


# ── Cards ─────────────────────────────────────────────────────────────────────

@router.post("/api/tracking/cards")
def create_card(
    request: Request,
    body: dict[str, Any] = Body(...),
    db: Session = Depends(get_db),
) -> dict:
    user = _require_user(request)
    col_id = int(body.get("columnId") or body.get("column_id", 0))
    col = db.execute(
        select(TrackingColumn)
        .where(TrackingColumn.id == col_id, TrackingColumn.user_id == user["id"])
    ).scalar_one_or_none()
    if not col:
        raise HTTPException(status_code=404, detail="Column not found")
    card = TrackingCard(
        user_id=user["id"],
        column_id=col_id,
        job_id=body.get("jobId") or body.get("job_id"),
        title=body.get("title", "Untitled"),
        company=body.get("company", ""),
        source=body.get("source", ""),
        url=body.get("url", ""),
        grade=body.get("grade", ""),
        salary_min=body.get("salaryMin") or body.get("salary_min"),
        salary_max=body.get("salaryMax") or body.get("salary_max"),
        salary_currency=body.get("salaryCurrency") or body.get("salary_currency"),
    )
    db.add(card)
    db.commit()
    db.refresh(card)
    return _card_to_dict(card)


@router.patch("/api/tracking/cards/{card_id}")
def update_card(
    request: Request,
    card_id: int,
    body: dict[str, Any] = Body(...),
    db: Session = Depends(get_db),
) -> dict:
    user = _require_user(request)
    card = db.execute(
        select(TrackingCard)
        .where(TrackingCard.id == card_id, TrackingCard.user_id == user["id"])
    ).scalar_one_or_none()
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")

    _FIELD_MAP: dict[str, tuple[str, Any]] = {
        "columnId":      ("column_id",    lambda v: int(v)),
        "column_id":     ("column_id",    lambda v: int(v)),
        "title":         ("title",        str),
        "company":       ("company",      str),
        "notes":         ("notes",        str),
        "coverLetter":   ("cover_letter", str),
        "cover_letter":  ("cover_letter", str),
        "grade":         ("grade",        str),
        "location":      ("location",     str),
        "salaryMin":     ("salary_min",   lambda v: int(v) if v is not None else None),
        "salaryMax":     ("salary_max",   lambda v: int(v) if v is not None else None),
        "salary_min":    ("salary_min",   lambda v: int(v) if v is not None else None),
        "salary_max":    ("salary_max",   lambda v: int(v) if v is not None else None),
        "salaryCurrency":("salary_currency", str),
        "appliedAt":     ("applied_at",   lambda v: datetime.fromtimestamp(v / 1000, tz=timezone.utc) if v else None),
        "stack":         ("stack_json",   json.dumps),
        "events":        ("events_json",  json.dumps),
    }
    for key, value in body.items():
        if key in _FIELD_MAP:
            attr, converter = _FIELD_MAP[key]
            setattr(card, attr, converter(value))

    card.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(card)
    return _card_to_dict(card)


@router.delete("/api/tracking/cards/{card_id}", status_code=204)
def delete_card(request: Request, card_id: int, db: Session = Depends(get_db)) -> None:
    user = _require_user(request)
    card = db.execute(
        select(TrackingCard)
        .where(TrackingCard.id == card_id, TrackingCard.user_id == user["id"])
    ).scalar_one_or_none()
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")
    db.delete(card)
    db.commit()


# ── Columns ───────────────────────────────────────────────────────────────────

@router.post("/api/tracking/columns")
def create_column(
    request: Request,
    body: dict[str, Any] = Body(...),
    db: Session = Depends(get_db),
) -> dict:
    user = _require_user(request)
    max_pos = db.execute(
        select(func.max(TrackingColumn.position))
        .where(TrackingColumn.user_id == user["id"])
    ).scalar() or 0
    col = TrackingColumn(
        user_id=user["id"],
        name=body.get("name", "New Column"),
        color=body.get("color", "#4493f8"),
        position=max_pos + 1,
    )
    db.add(col)
    db.commit()
    db.refresh(col)
    return _col_to_dict(col)


@router.patch("/api/tracking/columns/{col_id}")
def update_column(
    request: Request,
    col_id: int,
    body: dict[str, Any] = Body(...),
    db: Session = Depends(get_db),
) -> dict:
    user = _require_user(request)
    col = db.execute(
        select(TrackingColumn)
        .where(TrackingColumn.id == col_id, TrackingColumn.user_id == user["id"])
    ).scalar_one_or_none()
    if not col:
        raise HTTPException(status_code=404, detail="Column not found")
    if "name" in body:
        col.name = body["name"]
    if "color" in body:
        col.color = body["color"]
    if "position" in body:
        col.position = int(body["position"])
    db.commit()
    db.refresh(col)
    return _col_to_dict(col)


@router.delete("/api/tracking/columns/{col_id}", status_code=204)
def delete_column(request: Request, col_id: int, db: Session = Depends(get_db)) -> None:
    user = _require_user(request)
    col = db.execute(
        select(TrackingColumn)
        .where(TrackingColumn.id == col_id, TrackingColumn.user_id == user["id"])
    ).scalar_one_or_none()
    if not col:
        raise HTTPException(status_code=404, detail="Column not found")
    for card in db.execute(
        select(TrackingCard).where(TrackingCard.column_id == col_id, TrackingCard.user_id == user["id"])
    ).scalars().all():
        db.delete(card)
    db.delete(col)
    db.commit()


# ── HTMX: track from vacancy list ────────────────────────────────────────────

@router.post("/api/tracking/track-from-job", response_class=HTMLResponse)
async def track_from_job(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    user = get_current_user(request)
    if not user:
        return HTMLResponse('<button class="track-btn" disabled title="Sign in to track">+ Track</button>')

    form = await request.form()
    job_id = int(form.get("job_id", 0))

    existing = db.execute(
        select(TrackingCard)
        .where(TrackingCard.user_id == user["id"], TrackingCard.job_id == job_id)
    ).scalar_one_or_none()
    if existing:
        return HTMLResponse('<a class="tracked-pill" href="/tracking"><span class="chk">✓</span> Tracked</a>')

    col = db.execute(
        select(TrackingColumn)
        .where(TrackingColumn.user_id == user["id"])
        .order_by(TrackingColumn.position)
    ).scalars().first()
    if not col:
        return HTMLResponse('<button class="track-btn" disabled>No columns</button>')

    job = db.execute(select(JobRecord).where(JobRecord.id == job_id)).scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    db.add(TrackingCard(
        user_id=user["id"],
        column_id=col.id,
        job_id=job_id,
        title=job.title,
        company=job.company,
        source=job.source,
        url=job.link,
        grade=job.grade or "",
        salary_min=job.salary_min,
        salary_max=job.salary_max,
        salary_currency=job.salary_currency,
    ))
    db.commit()
    return HTMLResponse('<a class="tracked-pill" href="/tracking"><span class="chk">✓</span> Tracked</a>')


# ── CV upload / download ──────────────────────────────────────────────────────

@router.post("/api/tracking/cards/{card_id}/cv")
async def upload_cv(
    request: Request,
    card_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> dict:
    user = _require_user(request)
    card = db.execute(
        select(TrackingCard)
        .where(TrackingCard.id == card_id, TrackingCard.user_id == user["id"])
    ).scalar_one_or_none()
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")

    dest_dir = UPLOADS_DIR / str(user["id"])
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"card_{card_id}_{file.filename}"
    dest.write_bytes(await file.read())

    card.cv_filename = file.filename
    card.cv_path = str(dest)
    db.commit()
    return {"filename": file.filename, "url": f"/api/tracking/cards/{card_id}/cv"}


@router.get("/api/tracking/cards/{card_id}/cv")
def download_cv(request: Request, card_id: int, db: Session = Depends(get_db)) -> FileResponse:
    user = _require_user(request)
    card = db.execute(
        select(TrackingCard)
        .where(TrackingCard.id == card_id, TrackingCard.user_id == user["id"])
    ).scalar_one_or_none()
    if not card or not card.cv_path:
        raise HTTPException(status_code=404, detail="CV not found")
    return FileResponse(card.cv_path, filename=card.cv_filename)
