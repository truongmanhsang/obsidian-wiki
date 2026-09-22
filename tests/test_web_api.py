"""HTTP API contract tests for the memory web workspace."""

import pytest
from starlette.testclient import TestClient

from obsidian_memory_core.store import MemoryStore
from tests.support import valid_page_content


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("WIKI_JOB_DB", str(tmp_path / "jobs.db"))
    vault = tmp_path / "vault"
    store = MemoryStore(vault)
    store.ensure_ready()
    store.write(
        "people/test-user",
        valid_page_content(
            "people/test-user",
            "# Test User\n\n## Identity\n\nPrefers concise communication.\n\n## Related\n",
        ),
    )
    store.write(
        "concepts/retry-policy",
        valid_page_content(
            "concepts/retry-policy",
            "# Deployment Retry Policy\n\n## Summary\n\nRetry deployments carefully.\n\n## Related\n",
        ),
    )
    store.write(
        "answers/recovery",
        valid_page_content(
            "answers/recovery",
            "# Recovery Answer\n\nA durable answer.\n",
        ),
    )
    store.write(
        "preferences/response-style",
        valid_page_content(
            "preferences/response-style",
            "# Response Style\n\nPrefer concise responses.\n",
        ),
    )
    from web_api import create_web_app

    with TestClient(create_web_app(str(vault))) as test_client:
        yield test_client


def test_search_endpoint_returns_filtered_results(client):
    response = client.get("/api/search?q=communication&type=person&limit=5")

    assert response.status_code == 200
    assert response.json()["count"] == 1
    assert response.json()["results"][0]["path"] == "people/test-user.md"


def test_page_endpoint_rejects_paths_outside_curated_folders(client):
    response = client.get("/api/pages/../../etc/passwd")

    assert response.status_code in {400, 404}


def test_reflect_endpoint_returns_sources(client, monkeypatch):
    monkeypatch.setattr("web_api._run_reflection", lambda query, pages: "Grounded answer")

    response = client.post("/api/reflect", json={"query": "communication", "limit": 3})

    assert response.status_code == 200
    assert response.json()["reflection"] == "Grounded answer"
    assert response.json()["sources"]


def test_reflect_endpoint_requires_non_empty_query(client):
    response = client.post("/api/reflect", json={"query": "   "})

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_query"


def test_health_endpoint_reports_total_page_count(client):
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["pages"] == 4


def test_graph_endpoint_returns_vault_nodes(client):
    response = client.get("/api/graph")

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"]["nodes"] == 4
    assert len(payload["nodes"]) == 4
    assert isinstance(payload["links"], list)
    assert {node["type"] for node in payload["nodes"]} == {"person", "concept", "answer", "preference"}
    assert all({"id", "path", "title", "type", "updated", "tags"} <= set(node) for node in payload["nodes"])


def test_logs_endpoint_returns_recent_vault_activity(client):
    response = client.get("/api/logs?limit=10")

    assert response.status_code == 200
    payload = response.json()
    assert "log_tail" in payload
    assert "WRITE" in payload["log_tail"]
    assert payload["entries"]
    assert payload["entries"][-1]["created_at"]
    assert payload["entries"][-1]["kind"] == "WRITE"


def test_ingest_status_endpoint_is_read_only_and_empty_by_default(client):
    response = client.get("/api/ingest/status")

    assert response.status_code == 200
    assert response.json()["running"] is None
    assert response.json()["jobs"] == []
    assert client.post("/api/ingest/submit", json={}).status_code in {404, 405}


def test_pages_endpoint_filters_before_paginating(client):
    answer = client.get("/api/pages?type=answer&limit=1&offset=0")
    preference = client.get("/api/pages?type=preference&limit=1&offset=0")

    assert answer.status_code == 200
    assert answer.json()["total"] == 1
    assert answer.json()["pages"][0]["type"] == "answer"
    assert answer.json()["pages"][0]["path"] == "answers/recovery.md"

    assert preference.status_code == 200
    assert preference.json()["total"] == 1
    assert preference.json()["pages"][0]["type"] == "preference"
    assert preference.json()["pages"][0]["path"] == "preferences/response-style.md"


def test_pages_endpoint_supports_query_and_offset(client):
    response = client.get("/api/pages?q=retry&limit=1&offset=0")

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["offset"] == 0
    assert response.json()["limit"] == 1
    assert response.json()["pages"][0]["path"] == "concepts/retry-policy.md"


def test_resolve_endpoint_maps_wiki_links_to_canonical_pages(client):
    by_stem = client.get("/api/resolve?target=retry-policy&from=answers/recovery.md")
    by_title = client.get("/api/resolve?target=Deployment%20Retry%20Policy&from=answers/recovery.md")
    with_fragment = client.get("/api/resolve?target=concepts%2Fretry-policy.md%23Summary&from=answers/recovery.md")

    assert by_stem.status_code == 200
    assert by_stem.json() == {"path": "concepts/retry-policy.md", "fragment": ""}
    assert by_title.status_code == 200
    assert by_title.json()["path"] == "concepts/retry-policy.md"
    assert with_fragment.status_code == 200
    assert with_fragment.json() == {"path": "concepts/retry-policy.md", "fragment": "Summary"}


def test_resolve_endpoint_rejects_unknown_wiki_link(client):
    response = client.get("/api/resolve?target=does-not-exist&from=concepts/retry-policy.md")

    assert response.status_code == 404
    assert response.json()["error"] == "page_not_found"
