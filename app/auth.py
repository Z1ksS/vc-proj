from __future__ import annotations

import os
import secrets
from urllib.parse import urlencode

import requests as _req
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from app.db import SessionLocal
from app.models import TrackingColumn, User

_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")

router = APIRouter(prefix="/auth")


def get_current_user(request: Request) -> dict | None:
    try:
        uid = request.session.get("user_id")
    except Exception:
        return None
    if not uid:
        return None
    return {
        "id": uid,
        "name": request.session.get("user_name", ""),
        "email": request.session.get("user_email", ""),
        "avatar_url": request.session.get("user_avatar_url", ""),
    }


def _create_default_columns(db, user_id: int) -> None:
    defaults = [
        ("Applied", "#4493f8"),
        ("Phone Screen", "#e3b341"),
        ("Interview", "#bc8cff"),
        ("Offer", "#56d364"),
        ("Rejected", "#ff7b72"),
    ]
    for pos, (name, color) in enumerate(defaults):
        db.add(TrackingColumn(user_id=user_id, name=name, position=pos, color=color))
    db.commit()


@router.get("/login")
def login(request: Request) -> RedirectResponse:
    state = secrets.token_urlsafe(16)
    request.session["oauth_state"] = state
    redirect_uri = str(request.url_for("auth_callback"))
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
    }
    return RedirectResponse(f"{_AUTH_URL}?{urlencode(params)}")


@router.get("/callback", name="auth_callback")
def callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    if error or not code:
        return RedirectResponse("/")

    expected = request.session.pop("oauth_state", None)
    if not expected or state != expected:
        return RedirectResponse("/")

    redirect_uri = str(request.url_for("auth_callback"))

    token_resp = _req.post(
        _TOKEN_URL,
        data={
            "code": code,
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
        timeout=10,
    )
    if not token_resp.ok:
        return RedirectResponse("/")

    access_token = token_resp.json().get("access_token")

    user_resp = _req.get(
        _USERINFO_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10,
    )
    if not user_resp.ok:
        return RedirectResponse("/")

    info = user_resp.json()
    google_id = info.get("id", "")
    email = info.get("email", "")
    name = info.get("name") or email
    avatar_url = info.get("picture", "")

    with SessionLocal() as db:
        user = db.execute(
            select(User).where(User.google_id == google_id)
        ).scalar_one_or_none()
        if user is None:
            user = User(google_id=google_id, email=email, name=name, avatar_url=avatar_url)
            db.add(user)
            db.flush()
            _create_default_columns(db, user.id)
            db.commit()
        else:
            user.name = name
            user.avatar_url = avatar_url
            db.commit()

        request.session["user_id"] = user.id
        request.session["user_name"] = user.name
        request.session["user_email"] = user.email
        request.session["user_avatar_url"] = user.avatar_url

    return RedirectResponse("/tracking")


@router.post("/logout")
def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse("/", status_code=303)
