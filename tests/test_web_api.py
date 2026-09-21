"""HTTP API contract tests for the memory web workspace."""

import pytest
from starlette.testclient import TestClient

from obsidian_memory_core.store import MemoryStore
from tests.support import valid_page_content


@pytest.fixture()
def client(tmp_path):
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
