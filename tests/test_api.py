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
