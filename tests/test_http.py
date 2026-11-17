"""PoliteFetcher: caching, robots handling, bot-challenge refusal, rate limit. No network."""
import pytest

from researchmatch import http
from researchmatch.http import BlockedError, PoliteFetcher


class FakeResponse:
    def __init__(self, text, status=200):
        self.text, self.status_code, self.encoding = text, status, "utf-8"
        self.apparent_encoding = "utf-8"


class FakeSession:
    def __init__(self, pages):
        self.pages, self.calls, self.headers = pages, [], {}

    def get(self, url, timeout=None):
        self.calls.append(url)
        text, status = self.pages[url]
        return FakeResponse(text, status)


def make(tmp_path, pages):
    f = PoliteFetcher("TestUA/1.0", tmp_path, min_interval_s=1.0)
    f.session = FakeSession(pages)
    return f


def test_caches_and_reuses(tmp_path):
    f = make(tmp_path, {"https://a.test/robots.txt": ("", 404), "https://a.test/p": ("<html>ok</html>", 200)})
    html, path, from_cache = f.get("https://a.test/p", "d")
    assert html == "<html>ok</html>" and not from_cache and path.exists()
    assert path.with_suffix(".json").exists()
    _, _, from_cache = f.get("https://a.test/p", "d")
    assert from_cache
    assert f.session.calls.count("https://a.test/p") == 1


def test_robots_disallow(tmp_path):
    f = make(tmp_path, {"https://a.test/robots.txt": ("User-agent: *\nDisallow: /private", 200)})
    with pytest.raises(BlockedError):
        f.get("https://a.test/private/x", "d")


def test_robots_403_means_blocked(tmp_path):
    f = make(tmp_path, {"https://a.test/robots.txt": ("Forbidden", 403)})
    with pytest.raises(BlockedError):
        f.get("https://a.test/people", "d")


def test_bot_challenge_not_cached(tmp_path):
    # real page wraps the phrase across lines and has no other marker in some variants
    page = "<html><h1><span>Verifying you are\n            human.</span></h1></html>"
    f = make(tmp_path, {"https://a.test/robots.txt": ("", 404), "https://a.test/dir": (page, 200)})
    with pytest.raises(BlockedError):
        f.get("https://a.test/dir", "d")
    assert not any(tmp_path.rglob("*.html"))


def test_rate_limit_spacing(tmp_path, monkeypatch):
    clock = {"t": 100.0}
    sleeps = []
    monkeypatch.setattr(http.time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(http.time, "sleep", lambda s: (sleeps.append(s), clock.__setitem__("t", clock["t"] + s)))
    pages = {"https://a.test/robots.txt": ("", 404), "https://a.test/1": ("a", 200), "https://a.test/2": ("b", 200)}
    f = make(tmp_path, pages)
    f.get("https://a.test/1", "d")
    f.get("https://a.test/2", "d")
    # robots, /1, /2 on the same host -> two waits of a full second each
    assert sleeps == [pytest.approx(1.0), pytest.approx(1.0)]


def test_interval_below_one_second_rejected(tmp_path):
    with pytest.raises(ValueError):
        PoliteFetcher("UA", tmp_path, min_interval_s=0.5)
