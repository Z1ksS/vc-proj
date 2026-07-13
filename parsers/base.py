import logging
from abc import ABC, abstractmethod
from typing import List

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from models.job import Job

logger = logging.getLogger("job_vc.parser")


class BaseParser(ABC):
    timeout_seconds = 15

    def __init__(self) -> None:
        self.session = requests.Session()
        retry = Retry(
            total=3,
            backoff_factor=0.4,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("HEAD", "GET", "POST", "OPTIONS"),
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    _HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "uk-UA,uk;q=0.9,en-US;q=0.8",
    }

    def _get(self, url: str, **kwargs) -> requests.Response | None:
        kwargs.setdefault("timeout", self.timeout_seconds)
        kwargs.setdefault("headers", self._HEADERS)
        try:
            response = self.session.get(url, **kwargs)
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            logger.warning("GET failed url=%s reason=%s", url, _describe(exc))
            return None

    def _post(self, url: str, **kwargs) -> requests.Response | None:
        kwargs.setdefault("timeout", self.timeout_seconds)
        try:
            response = self.session.post(url, **kwargs)
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            logger.warning("POST failed url=%s reason=%s", url, _describe(exc))
            return None

    @abstractmethod
    def parse(self, keyword: str) -> List[Job]:
        pass


def _describe(exc: requests.RequestException) -> str:
    """Compact, log-friendly reason: HTTP status (plus edge/anti-bot hints) or exception type.

    On an HTTP error we also surface the ``Server`` header and any Cloudflare/challenge
    markers, so a 403 tells us whether it's a plain rate-limit or a bot-challenge (which
    retries/pacing can't clear — that needs a different egress IP)."""
    resp = getattr(exc, "response", None)
    if resp is None:
        return type(exc).__name__
    parts = [f"HTTP {resp.status_code}"]
    server = resp.headers.get("Server")
    if server:
        parts.append(f"server={server}")
    if resp.headers.get("cf-ray") or resp.headers.get("cf-mitigated"):
        parts.append("cloudflare")
    body = (resp.text or "")[:600].lower()
    if any(m in body for m in ("just a moment", "cf-challenge", "attention required", "cf-error-details")):
        parts.append("challenge-page")
    return " ".join(parts)
