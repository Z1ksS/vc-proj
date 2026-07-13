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
    """Compact, log-friendly reason: HTTP status when present, else exception type."""
    resp = getattr(exc, "response", None)
    if resp is not None:
        return f"HTTP {resp.status_code}"
    return type(exc).__name__
