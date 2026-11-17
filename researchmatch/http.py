"""Polite HTTP fetching: robots.txt check, >=1 s per-host spacing, descriptive UA, on-disk cache."""
from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.robotparser
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

# Markers of the Faculty of Arts & Science JS bot interstitial (and similar challenges).
_CHALLENGE_RE = re.compile(r"Verifying\s+you\s+are\s+human|AS_chal=", re.IGNORECASE)


class FetchError(RuntimeError):
    pass


class BlockedError(FetchError):
    """The site refused automated access (robots.txt disallow or a bot challenge).
    We do not try to get around this."""


def cache_path_for(cache_dir: Path, dept_id: str, url: str) -> Path:
    digest = hashlib.sha1(url.encode()).hexdigest()[:16]
    return cache_dir / dept_id / f"{digest}.html"


class PoliteFetcher:
    def __init__(self, user_agent: str, cache_dir: Path, min_interval_s: float = 1.0):
        if min_interval_s < 1.0:
            raise ValueError("min_interval_s must be >= 1.0")
        self.user_agent = user_agent
        self.cache_dir = cache_dir
        self.min_interval_s = min_interval_s
        self.session = requests.Session()
        self.session.headers["User-Agent"] = user_agent
        self._last_request: dict[str, float] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser] = {}

    # -- internals -----------------------------------------------------------------
    def _wait(self, host: str) -> None:
        last = self._last_request.get(host)
        if last is not None:
            delay = self.min_interval_s - (time.monotonic() - last)
            if delay > 0:
                time.sleep(delay)
        self._last_request[host] = time.monotonic()

    def _robots_for(self, url: str) -> urllib.robotparser.RobotFileParser:
        p = urlparse(url)
        base = f"{p.scheme}://{p.netloc}"
        if base not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            self._wait(p.netloc)
            try:
                r = self.session.get(f"{base}/robots.txt", timeout=30)
            except requests.RequestException as e:
                raise FetchError(f"Could not fetch robots.txt for {base}: {e}") from e
            if r.status_code in (401, 403):
                rp.disallow_all = True           # same convention as urllib.robotparser.read()
            elif r.status_code >= 400:
                rp.allow_all = True
            else:
                rp.parse(r.text.splitlines())
            self._robots[base] = rp
        return self._robots[base]

    # -- public --------------------------------------------------------------------
    def get(self, url: str, dept_id: str, refresh: bool = False) -> tuple[str, Path, bool]:
        """Returns (html, cache_path, from_cache)."""
        path = cache_path_for(self.cache_dir, dept_id, url)
        if path.exists() and not refresh:
            return path.read_text(encoding="utf-8"), path, True

        if not self._robots_for(url).can_fetch(self.user_agent, url):
            raise BlockedError(f"robots.txt disallows (or refuses) automated access to {url}")

        self._wait(urlparse(url).netloc)
        try:
            r = self.session.get(url, timeout=30)
        except requests.RequestException as e:
            raise FetchError(f"GET {url} failed: {e}") from e
        if r.status_code != 200:
            raise FetchError(f"GET {url} -> HTTP {r.status_code}")
        if r.encoding is None or r.encoding.lower() == "iso-8859-1":
            r.encoding = r.apparent_encoding
        html = r.text
        if _CHALLENGE_RE.search(html):
            raise BlockedError(f"{url} returned a bot-verification page; not caching it")

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html, encoding="utf-8")
        path.with_suffix(".json").write_text(json.dumps({
            "url": url,
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "status": r.status_code,
            "user_agent": self.user_agent,
        }, indent=2), encoding="utf-8")
        return html, path, False
