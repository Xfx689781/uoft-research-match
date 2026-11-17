"""API endpoints, with the bag-of-words embedder and a fake explainer (no model, no network)."""
import pytest
from fastapi.testclient import TestClient

from researchmatch.api import create_app
from researchmatch.explain import Explainer
from test_ranking import RANKING, BowEmbedder, conn  # noqa: F401  (reuses the ranking DB fixture)


class FakeExplainer(Explainer):
    def __init__(self, conn):
        super().__init__(conn, api_key="")
        self.calls = 0

    @property
    def enabled(self):
        return True

    def _client_or_none(self):
        return object()

    def _call(self, client, query, results):
        self.calls += 1
        return {r.professor.person_key: f"LLM: {r.professor.name} fits {query}" for r in results}


@pytest.fixture
def client(conn, tmp_path):  # noqa: F811
    db_path = conn.execute("PRAGMA database_list").fetchone()[2]
    app = create_app(db_path, BowEmbedder(), RANKING, explainer_factory=FakeExplainer)
    return TestClient(app)


def test_search_returns_fast_template_then_cached_llm(client):
    body = {"query": "reinforcement learning robots", "k": 3}
    r = client.post("/api/search", json=body).json()
    assert r["results"][0]["why_source"] == "template"
    first = r["results"][0]
    assert {"name", "appointments", "top_papers", "email", "match", "has_publications"} <= first.keys()

    ex = client.post("/api/explain", json=body).json()["explanations"]
    assert all(v["source"] == "llm" for v in ex.values())

    again = client.post("/api/search", json=body).json()
    assert again["results"][0]["why_source"] == "cache"
    assert again["results"][0]["why"].startswith("LLM:")


def test_department_filter(client):
    r = client.post("/api/search", json={"query": "inference", "departments": ["stats"]}).json()
    assert r["results"] and all(
        any(a["department_id"] == "stats" for a in x["appointments"]) for x in r["results"])


def test_validation(client):
    assert client.post("/api/search", json={"query": "x"}).status_code == 422
    assert client.post("/api/search", json={"query": "ok ok", "k": 500}).status_code == 422


def test_professor_detail_and_404(client):
    res = client.post("/api/search", json={"query": "reinforcement learning robots"}).json()["results"]
    pid = next(x["id"] for x in res if x["name"] == "Robo Learner")
    d = client.get(f"/api/professors/{pid}").json()
    assert d["name"] == "Robo Learner" and len(d["papers"]) == 3
    assert d["papers"][0]["year"] >= d["papers"][-1]["year"]           # newest first
    assert client.get("/api/professors/cs:nobody").status_code == 404


def test_meta(client):
    m = client.get("/api/meta").json()
    assert {d["id"] for d in m["departments"]} == {"cs", "math", "stats"}
    assert m["searchable_professors"] == 5 and m["data_last_updated"]


def test_search_is_rate_limited_per_visitor(conn, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setenv("SEARCH_PER_MINUTE", "2")
    db_path = conn.execute("PRAGMA database_list").fetchone()[2]
    c = TestClient(create_app(db_path, BowEmbedder(), RANKING, explainer_factory=FakeExplainer))
    body = {"query": "robots", "k": 1}
    alice, bob = {"x-forwarded-for": "1.1.1.1"}, {"x-forwarded-for": "2.2.2.2, 127.0.0.1"}
    assert [c.post("/api/search", json=body, headers=alice).status_code for _ in range(3)] == [200, 200, 429]
    assert c.post("/api/search", json=body, headers=bob).status_code == 200      # other visitors unaffected


def test_rate_limiter_window_slides():
    from researchmatch.api import RateLimiter
    t = [0.0]
    rl = RateLimiter(2, window=60, clock=lambda: t[0])
    assert rl.allow("a") and rl.allow("a") and not rl.allow("a")
    t[0] = 61
    assert rl.allow("a")


def test_daily_llm_cap_falls_back_to_templates(conn):  # noqa: F811
    from test_ranking import search
    ex = FakeExplainer(conn)
    ex.daily_limit = 1
    r1 = search(conn, "robotics", k=2)
    assert {s for _, s in ex.explain("robotics", r1).values()} == {"llm"}
    r2 = search(conn, "topology", k=2)
    assert {s for _, s in ex.explain("topology", r2).values()} == {"template"} and ex.calls == 1


def test_client_ip_ignores_spoofed_forwarded_entries():
    from types import SimpleNamespace
    from researchmatch.api import client_ip

    def req(peer, **h):
        return SimpleNamespace(client=SimpleNamespace(host=peer), headers=h)
    assert client_ip(req("127.0.0.1", **{"x-forwarded-for": "6.6.6.6, 5.5.5.5, 127.0.0.1"})) == "5.5.5.5"
    assert client_ip(req("127.0.0.1", **{"cf-connecting-ip": "4.4.4.4", "x-forwarded-for": "6.6.6.6"})) == "4.4.4.4"
    assert client_ip(req("8.8.8.8", **{"x-forwarded-for": "6.6.6.6"})) == "8.8.8.8"   # not via our proxy
    assert client_ip(req("127.0.0.1")) == "127.0.0.1"


def test_proxy_secret_required_and_visitor_ip_used(conn, monkeypatch):  # noqa: F811
    monkeypatch.setenv("PROXY_SECRET", "s3cret")
    monkeypatch.setenv("SEARCH_PER_MINUTE", "1")
    db_path = conn.execute("PRAGMA database_list").fetchone()[2]
    c = TestClient(create_app(db_path, BowEmbedder(), RANKING, explainer_factory=FakeExplainer))
    body = {"query": "robots", "k": 1}
    assert c.post("/api/search", json=body).status_code == 403
    assert c.get("/api/meta", headers={"x-proxy-secret": "wrong"}).status_code == 403
    ok = {"x-proxy-secret": "s3cret"}
    assert c.post("/api/search", json=body, headers={**ok, "x-visitor-ip": "1.1.1.1"}).status_code == 200
    assert c.post("/api/search", json=body, headers={**ok, "x-visitor-ip": "1.1.1.1"}).status_code == 429
    assert c.post("/api/search", json=body, headers={**ok, "x-visitor-ip": "2.2.2.2"}).status_code == 200
    assert c.get("/healthz").status_code == 200
