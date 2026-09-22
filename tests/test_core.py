"""Core vault, search, indexing, and navigation behavior tests."""

import asyncio
import importlib.util
import json
import re
import sqlite3
import sys
from pathlib import Path

import pytest

from tests.support import (
    FakeEmbedder,
    PLUGIN_DIR,
    _call,
    _load_module,
    _load_provider_for_tests,
    valid_page_content,
)

def test_default_vault_path_is_portable(monkeypatch, tmp_path):
    import obsidian_memory_core.config as config
    monkeypatch.setattr(config.Path, "home", staticmethod(lambda: tmp_path))
    assert config.default_vault_path() == str(tmp_path / "Documents" / "agent-vault")


def test_session_finalize_queues_old_session_in_plugin_worker(monkeypatch):
    module = _load_module()
    provider = module.ObsidianWikiMemoryProvider()
    calls = []

    class Manager:
        def submit(self, request_id=None, session_id=None):
            calls.append((request_id, session_id))
            return {"job_id": "ingest-local"}

    monkeypatch.setattr(provider, "_get_ingest_manager", lambda: Manager())
    provider.initialize("session-1")
    provider.on_session_end([])
    assert calls == [("session-1:completed", "session-1")]


def test_session_finalize_ignores_cron(monkeypatch):
    module = _load_module()
    provider = module.ObsidianWikiMemoryProvider()
    monkeypatch.setattr(provider, "_get_ingest_manager", lambda: (_ for _ in ()).throw(AssertionError()))
    provider._session_id = "cron_job_1"
    provider.on_session_end([])


def test_session_end_queues_completed_old_session(monkeypatch):
    module = _load_module()
    provider = module.ObsidianWikiMemoryProvider()
    calls = []

    class Manager:
        def submit(self, request_id=None, session_id=None):
            calls.append((request_id, session_id))
            return {"job_id": "ingest-local"}

    monkeypatch.setattr(provider, "_get_ingest_manager", lambda: Manager())
    provider.initialize("session-2")
    provider.on_session_end([])
    assert calls == [("session-2:completed", "session-2")]


def test_initialize_recovers_boundaries_with_plugin_manager(monkeypatch, tmp_path):
    module = _load_module()
    provider = module.ObsidianWikiMemoryProvider({
        "vault_path": str(tmp_path / "vault"),
        "access_mode": "direct",
    })
    calls = []

    class Manager:
        def resume_incomplete_jobs(self):
            calls.append("resume")
            return []

    monkeypatch.setattr(provider, "_get_ingest_manager", lambda: Manager())
    provider.initialize("session-a")
    provider.initialize("session-b")
    assert calls == ["resume"]


def test_session_switch_rebinds_provider_session(monkeypatch):
    module = _load_module()
    provider = module.ObsidianWikiMemoryProvider()
    provider._session_id = "old-session"
    provider.on_session_switch("new-session", reset=True)
    assert provider._session_id == "new-session"


def test_register_binds_both_boundary_hooks(monkeypatch):
    module = _load_module()
    calls = []

    class Context:
        def register_memory_provider(self, provider):
            pass

        def register_hook(self, name, callback):
            calls.append((name, callback.__name__))

    module.register(Context())
    assert [name for name, _ in calls] == ["on_session_finalize"]


def test_schema_instructs_direct_wrapper(monkeypatch, tmp_path):
    provider = _load_provider_for_tests(tmp_path)
    description = provider.get_tool_schemas()[0]["description"]
    assert "obsidian_wiki tool directly" in description
    assert "tool_search" in description


def _load_provider_for_tests(tmp_path):
    # The CI command adds the plugin directory itself to PYTHONPATH, not its
    # parent, so ``import obsidianwiki`` cannot resolve this directory as a
    # package. Use the same real-path loader as the fixture below.
    module = _load_module()
    return module.ObsidianWikiMemoryProvider({
        "vault_path": str(tmp_path / "vault"),
        "access_mode": "direct",
    })


def test_query_tokens_preserve_unicode_diacritics():
    from obsidian_memory_core.wiki.search import query_tokens

    assert query_tokens("partner birth date") == [
        "partner", "birth", "date",
    ]


def test_normalize_search_folds_latin_diacritics_and_unicode_forms():
    from obsidian_memory_core.wiki.intent import normalize_search

    original = "  Cà phê  "
    assert normalize_search(original) == "ca phe"
    assert normalize_search("Cafe\u0301") == "cafe"
    assert normalize_search("Ｍｅｍｏ") == "memo"
    assert original == "  Cà phê  "


def test_normalize_search_preserves_non_latin_combining_marks():
    from obsidian_memory_core.wiki.intent import normalize_search

    arabic = "مَرْحَبًا"
    assert normalize_search(arabic) == arabic


def test_search_matches_accented_and_unaccented_latin_metadata(tmp_path):
    from obsidian_memory_core import MemoryStore

    store = MemoryStore(tmp_path / "vault")
    store.ensure_ready()
    store.write(
        "concepts/coffee",
        valid_page_content(
            "concepts/coffee",
            "---\ntype: concept\naliases: [Cà phê]\ntags: [drink]\n"
            "search_terms: [café drink, beverage]\n---\n# Cà phê\n\nA café drink.\n",
        ),
    )

    for query in ("cà phê", "ca phe", "cafe drink", "beverage"):
        result = store.search(query, limit=5)
        assert result["results"]
        assert result["results"][0]["path"] == "concepts/coffee.md"


def test_search_rebuilds_legacy_fts_schema_with_projection_column(tmp_path):
    from obsidian_memory_core import MemoryStore

    store = MemoryStore(tmp_path / "vault")
    store.ensure_ready()
    store.write("concepts/legacy", valid_page_content("concepts/legacy", "# Legacy Search\n\nUnicode indexing.\n"))
    store.search("initial index build", limit=5)

    db = store.root / "fts.db"
    conn = sqlite3.connect(db)
    try:
        conn.execute("DROP TABLE fts_pages")
        conn.execute("DROP TABLE alembic_version")
        conn.execute("""CREATE VIRTUAL TABLE fts_pages USING fts5(
            path UNINDEXED, title, body, ptype UNINDEXED, updated UNINDEXED,
            tokenize='porter unicode61'
        )""")
        conn.commit()
    finally:
        conn.close()

    result = store.search("Unicode indexing", limit=5)

    assert result["results"]
    assert result["results"][0]["path"] == "concepts/legacy.md"


def test_fts_search_matches_metadata_in_search_projection(tmp_path):
    from obsidian_memory_core import MemoryStore

    store = MemoryStore(tmp_path / "vault")
    store.ensure_ready()
    store.write(
        "entities/metadata-only",
        valid_page_content(
            "entities/metadata-only",
            "---\n"
            "type: entity\n"
            "aliases: [Projection Alias]\n"
            "tags: [projection-test]\n"
            "search_terms: [unique projection keyword]\n"
            "---\n"
            "# Metadata Entity\n\nBody has no searchable phrase.\n",
        ),
    )

    result = store.search("unique projection keyword", limit=5)

    assert result["results"]
    assert result["results"][0]["path"] == "entities/metadata-only.md"
    assert result["results"][0]["match"] != "embedding"


def test_search_filter_normalization_and_page_matching():
    from obsidian_memory_core.wiki.search import (
        exact_page_match,
        normalize_search_filters,
        page_matches_filters,
    )

    page = {
        "rel": "people/example-partner.md",
        "title": "Example Partner",
        "stem": "example-partner",
        "ptype": "person",
        "updated": "2026-09-19",
        "meta": {
            "aliases": ["Partner Alias"],
            "tags": ["Family", "Profile"],
        },
    }

    filters = normalize_search_filters({
        "type": "PERSON",
        "tags": ["family", "profile"],
        "updated_after": "2026-09-01",
        "path_prefix": "./people/",
        "include_sources": False,
    })

    assert page_matches_filters(page, filters)
    assert page_matches_filters(
        {**page, "meta": {"tags": "family, profile", "aliases": "Partner Alias"}},
        filters,
    )
    assert exact_page_match(page, "partner alias")
    assert not page_matches_filters(page, {"type": "concept"})


def test_search_filters_and_source_opt_in(tmp_path):
    from obsidian_memory_core import MemoryStore

    store = MemoryStore(tmp_path / "vault")
    store.ensure_ready()
    store.write(
        "people/example-partner",
        valid_page_content(
            "people/example-partner",
            "---\n"
            "type: person\n"
            "aliases: [Partner Alias]\n"
            "tags: [family, profile]\n"
            "---\n"
            "# Example Partner\n\nPartner profile.\n",
        ),
    )
    store.write(
        "concepts/partner-guide",
        valid_page_content(
            "concepts/partner-guide",
            "---\n"
            "type: concept\n"
            "tags: [guide]\n"
            "---\n"
            "# Partner Guide\n\nPartner profile guide.\n",
        ),
    )
    store.vault.write_page(
        "sources/raw-partner.md",
        "---\n"
        "type: source\n"
        "updated: 2026-09-19\n"
        "---\n"
        "# Raw Partner\n\nPartner source evidence.\n",
        allow_source=True,
    )

    filtered = store.search(
        "partner",
        limit=5,
        filters={
            "type": "person",
            "tags": ["family"],
            "updated_after": "2026-09-19",
            "path_prefix": "people",
        },
    )
    assert filtered["results"][0]["path"] == "people/example-partner.md"
    assert all(row["type"] == "person" for row in filtered["results"])

    default_results = store.search("raw partner", limit=5)
    assert all(not row["path"].startswith("sources/") for row in default_results["results"])

    source_results = store.search(
        "raw partner",
        limit=5,
        filters={"include_sources": True},
    )
    assert any(row["path"] == "sources/raw-partner.md" for row in source_results["results"])


def test_exact_alias_is_marked_and_prioritized(tmp_path):
    from obsidian_memory_core import MemoryStore

    store = MemoryStore(tmp_path / "vault")
    store.ensure_ready()
    store.write(
        "people/example-partner",
        valid_page_content(
            "people/example-partner",
            "---\n"
            "type: person\n"
            "aliases: [Partner Alias]\n"
            "---\n"
            "# Example Partner\n\nPartner profile.\n",
        ),
    )
    store.write(
        "concepts/partner-alias-mentions",
        valid_page_content(
            "concepts/partner-alias-mentions",
            "# Partner Alias Mentions\n\n"
            "Partner Alias appears in this generic page several times: "
            "Partner Alias, Partner Alias.\n",
        ),
    )

    result = store.search("Partner Alias", limit=5)

    assert result["results"][0]["path"] == "people/example-partner.md"
    assert result["results"][0]["match"] == "exact"


def test_vietnamese_phrase_search_uses_boundaries_and_can_include_sources(tmp_path):
    from obsidian_memory_core import MemoryStore

    store = MemoryStore(tmp_path / "vault")
    store.ensure_ready()
    store.write(
        "concepts/trading-noise",
        valid_page_content(
            "concepts/trading-noise",
            "# Trading Noise\n\nThe balance was banked again after the gain.\n",
        ),
    )
    store.vault.write_page(
        "sources/sessions/2026/09/partner-birthday.md",
        "---\n"
        "type: source\n"
        "---\n"
        "# Hỏi ngày sinh bạn gái\n\nNgày sinh bạn gái được nhắc trong cuộc trò chuyện.\n",
        allow_source=True,
    )

    results = store.search("bạn gái", limit=10, filters={"include_sources": True})["results"]

    assert results[0]["path"] == "sources/sessions/2026/09/partner-birthday.md"
    assert all(row["path"] != "concepts/trading-noise.md" for row in results)

    curated_only = store.search("bạn gái", limit=10, filters={"include_sources": False}, precise=True)["results"]
    assert curated_only == []


def test_provider_schema_and_direct_search_forward_filters(tmp_path):
    provider = _load_provider_for_tests(tmp_path)
    provider.initialize(session_id="search-filter-test")
    properties = provider.get_tool_schemas()[0]["parameters"]["properties"]
    assert {
        "type", "tags", "updated_after", "path_prefix", "include_sources",
    }.issubset(properties)

    _call(
        provider,
        action="write",
        page="people/example-partner",
        content=(
            "---\ntype: person\ntags: [family]\n---\n"
            "# Example Partner\n\nPartner profile.\n"
        ),
    )
    _call(
        provider,
        action="write",
        page="concepts/partner-guide",
        content=(
            "---\ntype: concept\ntags: [guide]\n---\n"
            "# Partner Guide\n\nPartner guide.\n"
        ),
    )

    result = _call(
        provider,
        action="search",
        query="partner",
        type="person",
        tags=["family"],
        path_prefix="people",
    )

    assert result["results"]
    assert result["results"][0]["path"] == "people/example-partner.md"
    assert all(row["type"] == "person" for row in result["results"])


def test_alembic_migrations_run_in_order_once():
    from obsidian_memory_core.db.migrations import upgrade

    conn = sqlite3.connect(":memory:")
    upgrade(conn)
    upgrade(conn)
    rows = conn.execute(
        "SELECT version_num FROM alembic_version"
    ).fetchall()
    assert rows == [("fts_pages_virtual_table",)]
    assert conn.execute(
        "SELECT sql FROM sqlite_master WHERE name='fts_pages'"
    ).fetchone()[0].startswith("CREATE VIRTUAL TABLE")
    conn.close()


def test_log_database_is_migrated_and_uses_orm(tmp_path):
    from obsidian_memory_core.wiki.log import _ensure_db, append_log, _iter_log_rows
    from obsidian_memory_core.wiki.vault import WikiVault

    vault = WikiVault(str(tmp_path / "vault"))
    _ensure_db(vault)
    append_log(vault, "WRITE", "ORM migration")
    with sqlite3.connect(vault.root / "log.db") as conn:
        assert conn.execute("SELECT version_num FROM alembic_version").fetchall() == [("log_baseline",)]
    assert _iter_log_rows(vault)[0][2] == "ORM migration"


def test_query_features_are_derived_from_page_text_not_domain_vocabulary():
    from obsidian_memory_core.wiki.intent import analyze_query

    features = analyze_query("partner birth date")
    assert "partner birth date" in features.get("phrases", [])
    assert "birth date" in features.get("phrases", [])
    assert "relation" not in features


def test_default_embedding_index_is_multilingual_and_uses_model_calibrated_threshold():
    import obsidian_memory_core.wiki.fts as fts

    assert fts._EMBEDDING_MODEL == (
        "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    )
    assert fts._EMBEDDING_THRESHOLD == 0.25


def test_vietnamese_relationship_attribute_query_finds_curated_person_page(
    monkeypatch, tmp_path,
):
    from obsidian_memory_core import MemoryStore
    import obsidian_memory_core.wiki.fts as fts

    store = MemoryStore(tmp_path / "vault")
    store.ensure_ready()
    store.write(
        "people/example-partner",
        valid_page_content(
            "people/example-partner",
            "---\ntype: person\naliases: [Example Partner, Example Partner]\n"
            "relations:\n  - subject: test-user\n    relation: partner\n---\n"
            "# Example Partner\n\nPartner of Test User.\n\n"
            "Date of birth: 7 February 1997\n",
        ),
    )
    monkeypatch.setattr(fts, "_embedding_search", lambda *args, **kwargs: [])

    result = store.search("partner I birth date how many", limit=5)

    assert result["results"]
    assert result["results"][0]["path"] == "people/example-partner.md"
    assert result["results"][0]["type"] == "person"


def test_vector_embedding_fallback_runs_only_after_lexical_miss(monkeypatch, tmp_path):
    from obsidian_memory_core import MemoryStore
    import obsidian_memory_core.wiki.fts as fts

    store = MemoryStore(tmp_path / "vault")
    store.ensure_ready()
    store.write("people/example-partner", valid_page_content("people/example-partner", "# Example Partner\n\nPartner of Test User.\n"))
    monkeypatch.setattr(fts, "_get_embedder", lambda: FakeEmbedder())
    fts._reset_embedder_for_tests()

    result = store.search("partner of mine", limit=5)
    assert result["count"] == 1
    assert result["results"][0]["path"] == "people/example-partner.md"
    assert result["results"][0]["match"] == "embedding"


def test_vector_embedding_fallback_filters_below_threshold(monkeypatch, tmp_path):
    from obsidian_memory_core import MemoryStore
    import obsidian_memory_core.wiki.fts as fts

    store = MemoryStore(tmp_path / "vault")
    store.ensure_ready()
    store.write("concepts/trading", valid_page_content("concepts/trading", "# Trading\n\nRisk management for markets.\n"))
    monkeypatch.setattr(fts, "_get_embedder", lambda: FakeEmbedder())
    fts._reset_embedder_for_tests()

    result = store.search("cooking recipe", limit=5)
    assert result["count"] == 0


def test_hybrid_search_runs_embedding_on_weak_lexical_hits_and_merges(monkeypatch, tmp_path):
    from obsidian_memory_core import MemoryStore
    import obsidian_memory_core.wiki.fts as fts

    store = MemoryStore(tmp_path / "vault")
    store.ensure_ready()
    store.write("people/example-partner", valid_page_content("people/example-partner", "# Example Partner\n\nPartner of Test User.\n"))
    store.write("concepts/calendar", valid_page_content("concepts/calendar", "# Calendar\n\nBirthday reminders.\n"))
    calls = []

    def fake_embedding_search(vault, query, limit=5, threshold=None, pages=None):
        calls.append(query)
        return [{
            "path": "people/example-partner.md",
            "title": "Example Partner",
            "type": "person",
            "updated": "2026-08-26",
            "score": 0.91,
            "snippet": "",
            "match": "embedding",
        }]

    monkeypatch.setattr(fts, "_embedding_search", fake_embedding_search)
    result = store.search("birth date birthday", limit=5)

    assert calls == ["birth date birthday"]
    assert result["results"][0]["path"] == "people/example-partner.md"
    assert result["results"][0]["match"] == "embedding"
    assert result["results"][0]["score"] > 0.7


def test_hybrid_search_does_not_embed_exact_name_match(monkeypatch, tmp_path):
    from obsidian_memory_core import MemoryStore
    import obsidian_memory_core.wiki.fts as fts

    store = MemoryStore(tmp_path / "vault")
    store.ensure_ready()
    store.write(
        "people/example-partner",
        valid_page_content(
            "people/example-partner",
            "---\ntype: person\naliases: [Example Partner]\n---\n"
            "# Example Partner\n\nPartner of Test User.\n",
        ),
    )
    monkeypatch.setattr(
        fts, "_embedding_search",
        lambda *args, **kwargs: pytest.fail("exact name should not trigger embedding"),
    )

    result = store.search("Example Partner", limit=5)

    assert result["results"][0]["path"] == "people/example-partner.md"


def test_vector_embeddings_are_cached_and_reused(monkeypatch, tmp_path):
    from obsidian_memory_core import MemoryStore
    import obsidian_memory_core.wiki.fts as fts
    import sqlite3

    class CountingEmbedder(FakeEmbedder):
        calls = []

        def embed(self, texts):
            self.calls.append(list(texts))
            return super().embed(texts)

    embedder = CountingEmbedder()
    monkeypatch.setattr(fts, "_get_embedder", lambda: embedder)
    store = MemoryStore(tmp_path / "vault")
    store.ensure_ready()
    store.write("people/example-partner", valid_page_content("people/example-partner", "# Example Partner\n\nPartner of Test User.\n"))

    store.search("partner of mine", limit=5)
    assert len(embedder.calls) == 2
    assert len(embedder.calls[0]) == 1  # query only
    assert len(embedder.calls[1]) == 1  # one page on first cache fill

    store.search("partner of mine", limit=5)
    assert len(embedder.calls) == 3
    assert len(embedder.calls[2]) == 1  # query only; page vector was cached

    with sqlite3.connect(tmp_path / "vault" / "fts.db") as conn:
        row = conn.execute("SELECT COUNT(*) FROM embedding_pages").fetchone()
    assert row[0] == 1


def test_vault_path_precedence(monkeypatch, tmp_path):
    import obsidian_memory_core.config as config
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path / "env-vault"))
    assert config.vault_path({"vault_path": str(tmp_path / "config-vault")}) == str(tmp_path / "config-vault")
    assert config.vault_path({}) == str(tmp_path / "env-vault")
    monkeypatch.delenv("OBSIDIAN_VAULT_PATH")
    monkeypatch.setattr(config, "default_vault_path", lambda: str(tmp_path / "portable-vault"))
    assert config.vault_path({}) == str(tmp_path / "portable-vault")


def test_empty_expected_revision_is_treated_as_create(tmp_path):
    from obsidian_memory_core import MemoryStore

    store = MemoryStore(tmp_path / "vault")
    store.ensure_ready()
    created = store.write(
        "concepts/empty-revision-create",
        valid_page_content("concepts/empty-revision-create", "# Empty Revision Create\n\nA new page must accept an empty revision marker.\n"),
        expected_revision="",
    )
    assert created["status"] == "created"


def test_malformed_expected_revision_is_rejected_for_all_mutations(tmp_path):
    from obsidian_memory_core import MemoryStore, MemoryWriteError

    store = MemoryStore(tmp_path / "vault")
    store.ensure_ready()
    created = store.write("concepts/revision-format", valid_page_content("concepts/revision-format", "# Revision Format\n\nOriginal content.\n"))
    revision = store.read("concepts/revision-format")["revision"]
    malformed = revision[:-1]

    with pytest.raises(MemoryWriteError, match="invalid expected_revision format"):
        store.write(
            "concepts/revision-format",
            valid_page_content("concepts/revision-format", "# Revision Format\n\nChanged content.\n"),
            expected_revision=malformed,
        )
    with pytest.raises(MemoryWriteError, match="invalid expected_revision format"):
        store.append(
            "concepts/revision-format",
            "## Appended\n\nShould not persist.\n",
            expected_revision=malformed,
        )
    with pytest.raises(MemoryWriteError, match="invalid expected_revision format"):
        store.delete("concepts/revision-format", expected_revision="g" * 64)

    assert created["status"] == "created"
    assert store.read("concepts/revision-format")["revision"] == revision
    assert "Should not persist" not in store.read("concepts/revision-format")["content"]


def test_shared_core_write_revision_and_lock(tmp_path):
    from obsidian_memory_core import MemoryStore

    store = MemoryStore(tmp_path / "vault")
    store.ensure_ready()
    created = store.write("concepts/shared-core", valid_page_content("concepts/shared-core", "# Shared Core\n\nA durable memory page with enough content.\n"))
    assert created["status"] == "created"
    revision = store.read("concepts/shared-core")["revision"]
    updated = store.write(
        "concepts/shared-core",
        valid_page_content("concepts/shared-core", "# Shared Core\n\nUpdated durable memory content.\n"),
        expected_revision=revision,
    )
    assert updated["status"] == "updated"
    assert store.read("concepts/shared-core")["revision"] != revision

    with pytest.raises(Exception, match="revision conflict"):
        store.write("concepts/shared-core", valid_page_content("concepts/shared-core", "# Stale\n\nRejected stale update.\n"), expected_revision=revision)


def test_capture_measures_dialogue_not_markdown_metadata():
    hook_path = PLUGIN_DIR / "scripts" / "wiki_session_capture.py"
    spec = importlib.util.spec_from_file_location("wiki_session_capture_under_test", hook_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["wiki_session_capture_under_test"] = mod
    spec.loader.exec_module(mod)

    class Result:
        def __init__(self, rows):
            self.rows = rows

        def fetchall(self):
            return self.rows

        def fetchone(self):
            return self.rows[0] if self.rows else None

    class Cursor:
        def execute(self, query, params):
            if "FROM messages" in query:
                return Result([("user", "hello", "2026-08-25")])
            return Result([("Friendly greeting #29", "1787635072.919327")])

    result = mod.export_session(Cursor(), "session-id")
    assert result is not None
    markdown, turns, dialogue = result
    assert turns == 1
    assert dialogue == len("hello")
    assert len(markdown) > dialogue


def test_capture_quotes_frontmatter_aliases_with_yaml_special_chars():
    hook_path = PLUGIN_DIR / "scripts" / "wiki_session_capture.py"
    spec = importlib.util.spec_from_file_location("wiki_session_capture_frontmatter_test", hook_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["wiki_session_capture_frontmatter_test"] = mod
    spec.loader.exec_module(mod)

    class Result:
        def __init__(self, rows):
            self.rows = rows

        def fetchall(self):
            return self.rows

        def fetchone(self):
            return self.rows[0] if self.rows else None

    class Cursor:
        def execute(self, query, params):
            if "FROM messages" in query:
                return Result([("user", "A sufficiently long message", "2026-08-25")])
            return Result([("Hỏi ngày sinh bạn gái #7", "1787635072.919327")])

    result = mod.export_session(Cursor(), "20260827_092745_b8b2f291")
    assert result is not None
    markdown, _, _ = result
    assert "aliases:\n  - 'Hỏi ngày sinh bạn gái #7'" in markdown


def test_extract_status_is_not_inserted_inside_aliases_block(tmp_path):
    script = PLUGIN_DIR / "scripts" / "wiki_session_extract.py"
    spec = importlib.util.spec_from_file_location("wiki_session_extract_status_test", script)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["wiki_session_extract_status_test"] = mod
    spec.loader.exec_module(mod)

    source = tmp_path / "session.md"
    source.write_text(
        "---\n"
        "type: source\n"
        "updated: 2026-08-27\n"
        "tags:\n"
        "  - 'session'\n"
        "aliases:\n"
        "  - 'Hỏi ngày sinh bạn gái #7'\n"
        "---\n\n# Session\n",
        encoding="utf-8",
    )
    mod.update_extract_status(source, "success")
    text = source.read_text(encoding="utf-8")
    assert "extract_status: success\n" in text
    assert "aliases:\n  - 'Hỏi ngày sinh bạn gái #7'" in text
    assert "extract_status: success" in text
    assert "aliases:\nextract_status:" not in text


def test_store_ingest_status_preserves_aliases_block(tmp_path):
    from obsidian_memory_core import MemoryStore

    store = MemoryStore(tmp_path)
    page = "sources/sessions/2026/08/27/session.md"
    store.write_ingest(
        page,
        "---\ntype: source\nupdated: 2026-08-27\ntags:\n  - 'session'\naliases:\n  - 'Example #7'\n---\n\n# Session\n",
    )
    store.update_ingest_status(page, "success")
    text = (tmp_path / page).read_text(encoding="utf-8")
    assert "aliases:\n  - 'Example #7'" in text
    assert "extract_status: success" in text
    assert "aliases:\nextract_status:" not in text


def test_frontmatter_serializes_tags_and_aliases_as_safe_block_lists(tmp_path):
    from obsidian_memory_core.wiki.vault import _format_yaml_list

    rendered = _format_yaml_list("aliases", ["A #1", "O'Reilly", "[brackets]"])
    assert rendered == "aliases:\n  - 'A #1'\n  - 'O''Reilly'\n  - '[brackets]'"
    rendered = _format_yaml_list("tags", ["qa:automation", "#important"])
    assert rendered == "tags:\n  - 'qa:automation'\n  - '#important'"


def test_extract_dialogue_filter_ignores_short_source(tmp_path):
    script = PLUGIN_DIR / "scripts" / "wiki_session_extract.py"
    spec = importlib.util.spec_from_file_location("wiki_session_extract_filter_test", script)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["wiki_session_extract_filter_test"] = mod
    spec.loader.exec_module(mod)

    source = "---\ntype: source\n---\n\n# Session hello\n\n## User\n\nhello\n\n## Assistant\n\nHello there 👋\n"
    assert mod.dialogue_chars(source) < mod.MIN_DIALOGUE_CHARS


def test_shared_core_rejects_source_write_again(tmp_path):
    from obsidian_memory_core import MemoryStore

    store = MemoryStore(tmp_path / "vault")
    store.ensure_ready()
    with pytest.raises(Exception, match="read-only"):
        store.write("sources/nope", "# Nope\n\nSources remain read-only.\n")
class TestWritePath:
    def test_memory_system_overview_accumulates_backlinks_like_any_curated_page(self, provider):
        _call(provider, action="write", page="concepts/obsidian-wiki-memory-system",
              content="# Obsidian Wiki Memory System\n\nOverview.\n")
        _call(provider, action="write", page="entities/overview-client",
              content="# Overview Client\n\nLinks to [[concepts/obsidian-wiki-memory-system]].\n")
        overview = provider._get_vault().root / "concepts/obsidian-wiki-memory-system.md"
        assert "[[entities/overview-client.md|overview-client]]" in overview.read_text(encoding="utf-8")

    def test_write_creates_page_with_derived_frontmatter(self, provider):
        r = _call(provider, action="write", page="entities/A",
                  content="# A\n\nSome body line.\n")
        assert r["status"] == "created"
        assert r["type"] == "entity"
        text = open(r["path"]).read()
        assert "type: entity" in text and "updated: 20" in text

    def test_write_rejects_invalid_structure_without_creating_file(self, provider):
        result = _call(
            provider,
            action="write",
            page="concepts/bad-structure",
            content="# Bad Structure\n\nOnly an intro.\n",
            _raw_structure=True,
        )
        assert result["error"] == "structure_validation"
        assert "missing_profile_section" in result["message"]
        assert not (provider._get_vault().root / "concepts/bad-structure.md").exists()

    def test_write_accepts_valid_concept_structure(self, provider):
        result = _call(
            provider,
            action="write",
            page="concepts/good-structure",
            content=(
                "# Good Structure\n\nSummary.\n\n"
                "## Core Content\n\nDurable content.\n\n"
                "## Related\n\n- [[concepts/other]]\n"
            ),
        )
        assert result["status"] == "created"

    def test_write_updates_index_and_log(self, provider):
        _call(provider, action="write", page="entities/A",
              content="# A\n\nBody.\n")
        vault = provider._get_vault()
        idx = vault.index_path.read_text(encoding="utf-8")
        log = vault.log_tail(30)
        assert "[[entities/A.md|A]]" in idx or "[[entities/A|A]]" in idx
        assert "WRITE:" in log
        assert "INDEX_REBUILT" in log
        assert "pages=" in log
        assert "index_path=" in log
        assert "status=success" in log

    def test_sources_is_read_only(self, provider):
        r = _call(provider, action="write", page="sources/x",
                  content="# x\n\nnope nope nope\n")
        assert "error" in r and "read-only" in r["error"]

    def test_delete_requires_revision_and_reuses_index_log(self, provider):
        created = _call(provider, action="write", page="entities/delete-me",
                        content="# Delete Me\n\nTemporary page.\n")
        revision = _call(provider, action="read", page="entities/delete-me")["revision"]
        missing_revision = _call(provider, action="delete", page="entities/delete-me")
        assert missing_revision["error"] == "revision_conflict"
        deleted = _call(provider, action="delete", page="entities/delete-me",
                        expected_revision=revision, note="test deletion")
        assert deleted["status"] == "deleted"
        assert not __import__("pathlib").Path(created["path"]).exists()
        assert "delete-me" in provider._get_vault().index_path.read_text(encoding="utf-8")
        assert "DELETE:" in provider._get_vault().log_tail(30)

    def test_delete_rejects_sources_and_stale_revision(self, provider):
        _call(provider, action="write", page="entities/protected-delete",
              content="# Protected Delete\n\nBody.\n")
        stale = _call(provider, action="delete", page="entities/protected-delete",
                      expected_revision="0" * 64)
        assert stale["error"] == "revision_conflict"

    def test_wrong_folder_type_conflicts(self, provider):
        r = _call(provider, action="write", page="answers/x",
                  content="---\ntype: entity\n---\n\n# X\n\nbody\n")
        assert "error" in r

    def test_path_escape_rejected(self, provider):
        r = _call(provider, action="write", page="../evil",
                  content="# evil\n\nbad bad bad\n")
        assert "error" in r

    def test_short_content_rejected(self, provider):
        r = _call(provider, action="write", page="entities/x", content="# x\n", _raw_structure=True)
        assert "error" in r

    def test_append_preserves_existing_content_and_requires_revision(self, provider):
        _call(provider, action="write", page="concepts/append-me",
              content="# Append Me\n\nOriginal content.\n")
        revision = _call(provider, action="read", page="concepts/append-me")["revision"]
        appended = _call(provider, action="append", page="concepts/append-me",
                         content="## New Findings\n\nAppended content.\n",
                         expected_revision=revision)
        assert appended["status"] == "updated"
        result = _call(provider, action="read", page="concepts/append-me")
        assert "Original content." in result["content"]
        assert "## New Findings" in result["content"]
        assert "Appended content." in result["content"]
        assert result["content"].index("Original content.") < result["content"].index("Appended content.")

        missing_revision = _call(provider, action="append", page="concepts/append-me",
                                 content="Should be rejected.\n")
        assert missing_revision["error"] == "revision_conflict"

    def test_append_rejects_invalid_merged_document_without_mutation(self, provider):
        _call(
            provider,
            action="write",
            page="concepts/append-structure",
            content=(
                "# Append Structure\n\nSummary.\n\n"
                "## Core Content\n\nOriginal.\n\n## Related\n"
            ),
        )
        revision = _call(provider, action="read", page="concepts/append-structure")["revision"]
        result = _call(
            provider,
            action="append",
            page="concepts/append-structure",
            content="## Core Content\n\nDuplicate heading.\n",
            expected_revision=revision,
        )
        assert result["error"] == "structure_validation"
        assert "duplicate_heading" in result["message"]
        assert _call(provider, action="read", page="concepts/append-structure")["revision"] == revision

    def test_append_keeps_terminal_sections_at_end(self, provider):
        _call(
            provider,
            action="write",
            page="concepts/append-order",
            content=(
                "# Append Order\n\nSummary.\n\n"
                "## Core Content\n\nOriginal.\n\n## Related\n"
            ),
        )
        revision = _call(provider, action="read", page="concepts/append-order")["revision"]
        result = _call(
            provider,
            action="append",
            page="concepts/append-order",
            content="## Findings\n\nNew finding.\n",
            expected_revision=revision,
        )
        assert result["status"] == "updated"
        text = _call(provider, action="read", page="concepts/append-order")["content"]
        assert text.index("## Findings") < text.index("## Related")

    def test_append_rejects_missing_page(self, provider):
        result = _call(provider, action="append", page="concepts/does-not-exist",
                       content="New content.\n", expected_revision="anything")
        assert "error" in result

    def test_append_is_idempotent_for_existing_content(self, provider):
        _call(provider, action="write", page="concepts/append-idempotent",
              content="# Append Idempotent\n\nOriginal content.\n")
        revision = _call(provider, action="read", page="concepts/append-idempotent")["revision"]
        first = _call(provider, action="append", page="concepts/append-idempotent",
                      content="## Finding\n\nThe same finding.\n",
                      expected_revision=revision)
        second_revision = _call(provider, action="read", page="concepts/append-idempotent")["revision"]
        second = _call(provider, action="append", page="concepts/append-idempotent",
                       content="## Finding\n\nThe same finding.\n",
                       expected_revision=second_revision)
        result = _call(provider, action="read", page="concepts/append-idempotent")
        assert first["status"] == "updated"
        assert second["status"] == "unchanged"
        assert result["content"].count("The same finding.") == 1
        assert second["revision"] == second_revision

    def test_append_rejects_payload_containing_entire_previous_page(self, provider):
        _call(provider, action="write", page="concepts/append-full-page",
              content="# Append Full Page\n\nOriginal content.\n")
        old = _call(provider, action="read", page="concepts/append-full-page")
        accidental_payload = old["content"] + "\n## New Finding\n\nMore content.\n"
        result = _call(provider, action="append", page="concepts/append-full-page",
                       content=accidental_payload, expected_revision=old["revision"])
        assert "entire existing page" in result["error"]
        verified = _call(provider, action="read", page="concepts/append-full-page")
        assert verified["content"].count("Original content.") == 1

    def test_append_rejects_a_write_that_does_not_persist(self, tmp_path):
        from obsidian_memory_core.store import MemoryStore, MemoryWriteError

        store = MemoryStore(str(tmp_path / "vault"))
        store.ensure_ready()
        store.write("concepts/persist-check", valid_page_content("concepts/persist-check", "# Persist Check\n\nOriginal content.\n"))
        page = store.read("concepts/persist-check")
        original_write_page = store.vault.write_page

        def write_then_restore(*args, **kwargs):
            result = original_write_page(*args, **kwargs)
            path = store._page_path("concepts/persist-check")
            path.write_text(page["content"], encoding="utf-8")
            return result

        store.vault.write_page = write_then_restore
        with pytest.raises(MemoryWriteError, match="did not persist"):
            store.append(
                "concepts/persist-check",
                "## New Finding\n\nAppended content.\n",
                expected_revision=page["revision"],
            )

    def test_auto_backlinks_stay_before_final_related_section(self, provider):
        _call(provider, action="write", page="concepts/related-neighbor",
              content="# Related Neighbor\n\nNeighbor content.\n")
        _call(provider, action="write", page="concepts/backlink-target",
              content=(
                  "# Backlink Target\n\nTarget content.\n\n"
                  "## Core Content\n\nTarget details.\n\n"
                  "## Related\n\n- [[concepts/related-neighbor|Related Neighbor]]\n"
              ))
        _call(provider, action="write", page="entities/backlink-source",
              content="# Backlink Source\n\nLinks to [[concepts/backlink-target]].\n")

        target = _call(provider, action="read", page="concepts/backlink-target")["content"]
        assert "## Linked from" in target
        assert target.index("## Linked from") < target.index("## Related")
        h2 = re.findall(r"(?m)^##\s+(.+?)\s*$", target)
        assert h2[-1] == "Related"
        related = target.split("## Related", 1)[1]
        assert "[[concepts/related-neighbor|Related Neighbor]]" in related

    def test_append_preserves_content_when_page_has_auto_backlinks(self, provider):
        _call(provider, action="write", page="concepts/append-with-backlinks",
              content="# Append With Backlinks\n\nOriginal content.\n")
        _call(provider, action="write", page="concepts/append-link-source",
              content="# Append Link Source\n\n[[concepts/append-with-backlinks]]\n")
        old = _call(provider, action="read", page="concepts/append-with-backlinks")
        result = _call(provider, action="append", page="concepts/append-with-backlinks",
                       content="## New Finding\n\nAppended content.\n",
                       expected_revision=old["revision"])
        assert result["status"] == "updated"
        verified = _call(provider, action="read", page="concepts/append-with-backlinks")
        assert "Appended content." in verified["content"]
        assert verified["content"].index("Appended content.") < verified["content"].index("## Linked from")

    def test_append_inserts_new_sections_before_related_and_linked_from(self, provider):
        _call(provider, action="write", page="answers/append-related",
              content="# Append Related\n\n## Existing analysis\n\nDetails.\n\n## Sources\n\n- Existing source\n\n## Related\n\n- [[concepts/obsidian-wiki-index]]\n")
        old = _call(provider, action="read", page="answers/append-related")
        _call(provider, action="append", page="answers/append-related",
              content="## Historical comparison\n\nNew comparison.",
              expected_revision=old["revision"])
        verified = _call(provider, action="read", page="answers/append-related")
        text = verified["content"]
        assert text.index("## Historical comparison") < text.index("## Sources")
        assert text.index("## Historical comparison") < text.index("## Related")
        assert text.count("## Sources") == 1
        assert text.count("## Related") == 1

    def test_update_stamps_new_date(self, provider):
        _call(provider, action="write", page="entities/a1",
              content="# A1\n\nfirst body\n")
        revision = _call(provider, action="read", page="entities/a1")["revision"]
        _call(provider, action="write", page="entities/a1",
              content="# A1\n\nsecond body\n", expected_revision=revision)
        r = _call(provider, action="read", page="entities/a1")
        assert r["content"].count("updated: 20") == 1
        assert "second body" in r["content"]

    def test_write_without_frontmatter_auto_fills_aliases_tags(self, provider):
        # A page written with NO frontmatter must get a non-empty aliases+tags
        # trio derived from its title/filename/type (no LLM, deterministic).
        r = _call(provider, action="write", page="entities/quantum-flux",
                  content="# Quantum Flux\n\nresearch on flux capacitors\n")
        assert r["status"] == "created"
        text = open(r["path"]).read()
        assert "tags:" in text and "aliases:" in text
        # aliases should include the H1 title
        assert "Quantum Flux" in text
        # no empty brackets
        assert "aliases: []" not in text
        assert "tags: []" not in text
        # The page must lint clean (no aliases_wiped / missing frontmatter).
        lint = json.loads(provider.handle_tool_call("obsidian_wiki", {"action": "lint"}))
        assert "aliases_wiped" not in lint.get("problems", {}), lint
        assert "missing_frontmatter" not in lint.get("problems", {}), lint

    def test_write_with_empty_aliases_tags_auto_fills(self, provider):
        # A page whose frontmatter leaves aliases/tags empty must be auto-filled
        # on write, not left as [].
        r = _call(provider, action="write", page="concepts/grid-risk",
                  content="---\ntype: concept\nupdated: 2026-08-26\ntags: []\naliases: []\n---\n\n# Grid Risk\n\ngrid DCA risk notes\n")
        assert r["status"] == "created"
        text = open(r["path"]).read()
        assert "aliases: []" not in text
        assert "tags: []" not in text
        assert "Grid Risk" in text
        lint = json.loads(provider.handle_tool_call("obsidian_wiki", {"action": "lint"}))
        assert "aliases_wiped" not in lint.get("problems", {}), lint

    def test_auto_fill_tags_are_bounded_normalized_and_filtered(self, provider):
        # Four useful filename keywords max, lowercase, no dates/stopwords.
        r = _call(provider, action="write",
                  page="concepts/alpha-and-the-beta-2026-08-long-tail-extra",
                  content="# Alpha Beta\n\nlong tag normalization test\n")
        text = open(r["path"]).read()
        tags_line = next(line for line in text.splitlines() if line.startswith("tags:"))
        assert tags_line == "tags: ['concept', 'alpha', 'beta', 'long', 'tail']"
        assert "the" not in tags_line and "and" not in tags_line
        assert "2026" not in tags_line and "08" not in tags_line

    def test_auto_fill_handles_missing_h1_and_duplicate_title(self, provider):
        # No H1 still gets a filename alias; identical H1/filename is deduped.
        no_h1 = _call(provider, action="write", page="entities/no-heading",
                      content="body without a heading but enough content\n",
                      _raw_structure=True)
        assert no_h1["error"] == "structure_validation"
        dup = _call(provider, action="write", page="entities/same-title",
                    content="# Same Title\n\nbody for duplicate alias check\n")
        dup_text = open(dup["path"]).read()
        assert "aliases: ['Same Title', 'Same Title']" not in dup_text
        assert "aliases: ['Same Title']" in dup_text


class TestReadSearch:
    def test_read_miss_suggests_similar(self, provider):
        _call(provider, action="write", page="entities/project-alpha-x",
              content="# Project Alpha X\n\ngeneric project alpha details\n")
        r = _call(provider, action="read", page="entities/projectalphax")
        assert "error" in r
        assert r.get("similar")

    def test_search_ranks_title_hits_higher(self, provider):
        _call(provider, action="write", page="entities/alpha",
              content="# Alpha\n\nquantum flux capacitor mentions\n")
        _call(provider, action="write", page="entities/beta",
              content="# Beta\n\nsomething else entirely quantum\n")
        r = _call(provider, action="search", query="alpha quantum")
        paths = [x["path"] for x in r["results"]]
        assert paths[0] == "entities/alpha.md"

    def test_search_handles_unicode_names_and_exact_phrases(self, provider):
        _call(provider, action="write", page="people/test-user-partner",
              content="---\ntype: person\nupdated: 2026-08-26\ntags: [people]\naliases: [Example Partner, Example Partner]\n---\n\n# Example Partner\n\nDate of birth: 7 February 1997.\n")
        r = _call(provider, action="search", query="Example Partner birth date how many", limit=5)
        assert r["results"]
        assert r["results"][0]["path"] == "people/test-user-partner.md"


class TestLint:
    def test_lint_reports_structure_errors_without_rewriting(self, tmp_path):
        from obsidian_memory_core.wiki.vault import WikiVault

        vault = WikiVault(str(tmp_path / "vault"))
        vault.ensure_skeleton()
        path = vault.root / "concepts/legacy.md"
        original = "# Legacy\n\nOld content without the required profile sections.\n"
        path.write_text(original, encoding="utf-8")

        result = vault.lint()

        assert result["problems"]["structure"]
        finding = next(
            item for item in result["problems"]["structure"]
            if item["path"] == "concepts/legacy.md"
        )
        issue_codes = {
            issue["code"]
            for issue in finding["errors"] + finding["warnings"]
        }
        assert "missing_profile_section" in issue_codes
        assert path.read_text(encoding="utf-8") == original

    def _write_without_auto_heal(self, provider, page, content):
        vault = provider._get_vault()
        vault._auto_heal_in_progress = True
        original_rebuild = vault.rebuild_index
        vault.rebuild_index = lambda: None
        try:
            return _call(provider, action="write", page=page, content=content)
        finally:
            vault.rebuild_index = original_rebuild
            vault._auto_heal_in_progress = False

    def test_orphan_fix_dry_run_targets_root_index(self, provider):
        self._write_without_auto_heal(
            provider,
            "entities/seed-page",
            "# Seed Page\n\nExisting content.\n",
        )
        self._write_without_auto_heal(
            provider,
            "entities/orphan-page",
            "# Orphan Page\n\nStandalone content.\n",
        )
        vault = provider._get_vault()
        before = vault.index_path.read_text(encoding="utf-8")
        result = vault.fix_orphans(dry_run=True)
        assert result["dry_run"] is True
        assert result["plan"][0]["index"] == "index.md"
        assert vault.index_path.read_text(encoding="utf-8") == before

    def test_orphan_fix_updates_root_index_and_is_idempotent(self, provider):
        self._write_without_auto_heal(
            provider,
            "entities/seed-page",
            "# Seed Page\n\nExisting content.\n",
        )
        self._write_without_auto_heal(
            provider,
            "entities/orphan-page",
            "# Orphan Page\n\nStandalone content.\n",
        )
        vault = provider._get_vault()
        first = vault.fix_orphans(dry_run=False)
        assert first["fixed"] == 2
        assert "[[entities/orphan-page|Orphan Page]]" in vault.index_path.read_text()
        second = vault.fix_orphans(dry_run=False)
        assert second["fixed"] == 0

    def test_write_preserves_optional_metadata(self, provider):
        result = _call(
            provider,
            action="write",
            page="concepts/former-hub",
            content=(
                "---\n"
                "lint_hub: true\n"
                "lint_keywords: [old-topic]\n"
                "lint_priority: 10\n"
                "---\n\n"
                "# Former Hub\n\nOrdinary concept content.\n"
            ),
        )
        text = Path(result["path"]).read_text(encoding="utf-8")
        assert "lint_hub: true" in text
        assert "lint_keywords:" in text
        assert "old-topic" in text
        assert "lint_priority: 10" in text

    def test_orphan_and_broken_link_detected(self, provider):
        # lone page with a link to nowhere
        _call(provider, action="write", page="entities/lone",
              content="# Lone\n\ntargets [[entities/missing-target]] here\n")
        lint = json.loads(provider.handle_tool_call("obsidian_wiki",
                                                    {"action": "lint"}))
        assert not lint["clean"]
        assert any("missing-target" in b for b in lint["problems"]["broken_links"])

    def test_weak_connectivity_flagged(self, provider):
        # Dead-end chain: B links nowhere and only A references it.
        # Both end up with total degree 1 (<2) -> weak_connectivity warning.
        _call(provider, action="write", page="entities/chain-a",
              content="# ChainA\n\npoints at [[entities/chain-b|B]] only\n")
        _call(provider, action="write", page="entities/chain-b",
              content="# ChainB\n\nstandalone leaf page with no links\n")
        lint = json.loads(provider.handle_tool_call("obsidian_wiki",
                                                    {"action": "lint"}))
        assert not lint["clean"]
        assert "weak_connectivity" in lint["problems"]
        assert any("chain-b" in w for w in lint["problems"]["weak_connectivity"])

    def test_healthy_triangle_passes(self, provider):
        _call(provider, action="write", page="entities/tri-a",
              content="# TriA\n\nlinks [[entities/tri-b|B]] and [[entities/tri-c|C]]\n")
        _call(provider, action="write", page="entities/tri-b",
              content="# TriB\n\nlinks back to [[entities/tri-a|A]]\n")
        _call(provider, action="write", page="entities/tri-c",
              content="# TriC\n\nalso links [[entities/tri-a|A]]\n")
        lint = json.loads(provider.handle_tool_call("obsidian_wiki",
                                                    {"action": "lint"}))
        assert lint["clean"], lint


    def test_stale_claims_ignores_mention_in_other_page_log(self, provider):
        # Regression: a page whose stem is merely mentioned inside another
        # page's WRITE line must NOT be flagged as stale. Only a WRITE/UPDATE
        # line that names the page explicitly counts.
        _call(provider, action="write", page="entities/test-user-bot",
              content="# Test User Bot\n\nlinks [[entities/test-user-partner|partner]]\n")
        # Another page's log line mentions test-user-bot in passing.
        vault = provider._get_vault()
        vault.append_log("WRITE", "updated entities/test-user-partner with note about test-user-bot meeting")
        lint = json.loads(provider.handle_tool_call("obsidian_wiki",
                                                    {"action": "lint"}))
        probs = lint.get("problems", {})
        assert "stale_claims" not in probs, probs
        # The page itself is healthy (has inbound link).
        assert lint["clean"] or "weak_connectivity" in probs or "orphans" in probs, lint

    def test_aliases_wiped_only_on_explicit_guard_event(self, provider):
        # Regression: when a page is written with empty aliases, write_page now
        # AUTO-FILLS them from the title/filename, so the page is never left
        # empty and aliases_wiped must NOT fire for a page that merely got
        # auto-filled. A genuine guard event (preserving prior aliases) still
        # only matters if the page is actually empty on disk.
        r = _call(provider, action="write", page="people/example-automation-specialist-example-project",
                  content="---\ntype: person\nupdated: 2026-08-01\ntags: [example-project]\naliases: []\n---\n\n# Mr. Example Automation Specialist\n\nQA automation engineer.\n")
        text = open(r["path"]).read()
        # Auto-fill kicked in: aliases no longer empty.
        assert "aliases: []" not in text, text
        vault = provider._get_vault()
        # A different page's WRITE line happens to mention example-automation-specialist-example-project.
        vault.append_log("WRITE", "updated entities/example-project, referenced example-automation-specialist-example-project in team list")
        lint1 = json.loads(provider.handle_tool_call("obsidian_wiki",
                                                      {"action": "lint"}))
        assert "aliases_wiped" not in lint1.get("problems", {}), lint1

        # Now a genuine guard event naming the exact file. Because the page was
        # already auto-filled (not empty), aliases_wiped must still NOT fire.
        vault.append_log(
            "WRITE",
            "frontmatter guard: preserving aliases ['Example Automation Specialist'] for "
            f"{vault.root / 'people' / 'example-automation-specialist-example-project.md'} (would have wiped to [])",
        )
        lint2 = json.loads(provider.handle_tool_call("obsidian_wiki",
                                                      {"action": "lint"}))
        assert "aliases_wiped" not in lint2.get("problems", {}), lint2

    def test_md_suffix_links_resolve(self, provider):
        _call(provider, action="write", page="entities/e2",
              content="# E2\n\nsee [[entities/e3.md]] please\n")
        _call(provider, action="write", page="entities/e3",
              content="# E3\n\nsee [[entities/e2|e two]] back\n")
        lint = json.loads(provider.handle_tool_call("obsidian_wiki",
                                                    {"action": "lint"}))
        assert lint["clean"], lint


class TestLLMGeneration:
    def test_generation_module_exports_only_index_proposal(self):
        import obsidian_memory_core.wiki.generation as generation

        assert not hasattr(generation, "generate_hub_proposal")
        assert hasattr(generation, "generate_index_proposal")

    def test_index_manifest_has_no_hub_metadata(self, provider):
        manifest = provider._get_vault()._index_manifest()
        assert all("lint_hub" not in page for page in manifest)

    def test_index_proposal_rejects_unknown_wikilink(self):
        from obsidian_memory_core.wiki.generation import generate_index_proposal

        result = generate_index_proposal(
            [{"path": "entities/gold-bot.md", "title": "Gold Bot", "type": "entity"}],
            run_llm=lambda _: {
                "content": (
                    "---\n"
                    "title: Agent Vault Index\n"
                    "type: index\n"
                    "updated: 2026-09-10\n"
                    "tags: [wiki, index]\n"
                    "---\n\n"
                    "[[entities/missing]]"
                )
            },
        )
        assert result["error"] == "invalid_link"

    def test_index_proposal_rejects_duplicate_page_links(self):
        from obsidian_memory_core.wiki.generation import generate_index_proposal

        result = generate_index_proposal(
            [{"path": "entities/gold-bot.md", "title": "Gold Bot", "type": "entity"}],
            run_llm=lambda _: {
                "content": (
                    "---\n"
                    "title: Agent Vault Index\n"
                    "type: index\n"
                    "updated: 2026-09-10\n"
                    "tags: [wiki, index]\n"
                    "---\n\n"
                    "[[entities/gold-bot]]\n[[entities/gold-bot]]"
                )
            },
        )
        assert result["error"] == "duplicate_link"

    def test_llm_exception_returns_stable_error(self):
        from obsidian_memory_core.wiki.generation import generate_index_proposal

        def fail(_):
            raise TimeoutError("model unavailable")

        result = generate_index_proposal([], run_llm=fail)
        assert result["error"] == "llm_unavailable"


class TestLLMIndexLifecycle:
    def test_blank_first_write_replaces_skeleton_index_with_llm_index(
        self, provider, monkeypatch
    ):
        vault = provider._get_vault()
        generated = []

        def fake_index(manifest, run_llm=None):
            generated.append(manifest)
            links = "\n".join(
                f"- [[{page['path']}|{page['title']}]]" for page in manifest
            )
            return {
                "content": (
                    "---\n"
                    "title: Agent Vault Index\n"
                    "type: index\n"
                    "updated: 2026-09-10\n"
                    "tags: [wiki, index]\n"
                    "---\n\n"
                    "# LLM Index\n\n"
                    f"{links}\n"
                )
            }

        monkeypatch.setitem(
            type(vault).ensure_index_generated.__globals__,
            "generate_index_proposal",
            fake_index,
        )
        _call(provider, action="write", page="entities/first-page",
              content="# First Page\n\nFirst content.\n")
        index = (provider._get_vault().root / "index.md").read_text(encoding="utf-8")
        assert "# LLM Index" in index
        assert generated

    def test_existing_index_is_refreshed_after_new_page(self, provider, monkeypatch):
        vault = provider._get_vault()
        calls = []

        def fake_index(manifest, run_llm=None):
            calls.append(manifest)
            links = "\n".join(
                f"- [[{page['path']}|{page['title']}]]" for page in manifest
            )
            return {
                "content": (
                    "---\n"
                    "title: Agent Vault Index\n"
                    "type: index\n"
                    "updated: 2026-09-10\n"
                    "tags: [wiki, index]\n"
                    "---\n\n"
                    "# LLM Index\n\n"
                    f"{links}\n"
                )
            }

        monkeypatch.setitem(
            type(vault).ensure_index_generated.__globals__,
            "generate_index_proposal",
            fake_index,
        )
        _call(provider, action="write", page="entities/first-page",
              content="# First Page\n\nFirst content.\n")
        index_path = provider._get_vault().root / "index.md"
        original = index_path.read_text(encoding="utf-8")
        _call(provider, action="write", page="entities/second-page",
              content="# Second Page\n\nSecond content.\n")
        assert len(calls) == 1
        refreshed = index_path.read_text(encoding="utf-8")
        assert refreshed != original
        assert "[[entities/second-page.md|Second Page]]" in refreshed
        assert "Pages: 3" in refreshed

    def test_missing_index_in_established_vault_is_generated(self, provider, monkeypatch):
        vault = provider._get_vault()
        _call(provider, action="write", page="entities/first-page",
              content="# First Page\n\nFirst content.\n")
        vault.index_path.unlink()
        vault.ensure_skeleton()
        calls = []

        def fake_index(manifest, run_llm=None):
            calls.append(manifest)
            return {
                "content": (
                    "---\n"
                    "title: Agent Vault Index\n"
                    "type: index\n"
                    "updated: 2026-09-10\n"
                    "tags: [wiki, index]\n"
                    "---\n\n"
                    "# Recreated LLM Index\n"
                    "- [[entities/first-page|First Page]]\n"
                )
            }

        monkeypatch.setitem(
            type(vault).ensure_index_generated.__globals__,
            "generate_index_proposal",
            fake_index,
        )
        _call(provider, action="write", page="entities/second-page",
              content="# Second Page\n\nSecond content.\n")
        assert len(calls) == 1
        assert "# Recreated LLM Index" in vault.index_path.read_text(encoding="utf-8")


class TestCategoryNavigation:
    @staticmethod
    def _vault(tmp_path):
        from obsidian_memory_core.wiki.vault import WikiVault
        vault = WikiVault(str(tmp_path / "category-vault"))
        vault.ensure_skeleton()
        return vault

    @staticmethod
    def _page(title, tag):
        return (
            "---\n"
            "type: concept\n"
            f"tags: [{tag}]\n"
            f"aliases: [{title}]\n"
            "---\n\n"
            f"# {title}\n\nA {tag} page.\n\n"
            "## Core Content\n\nCategory test content.\n\n"
            "## Related\n"
        )

    def test_reuses_matching_category_index(self, tmp_path):
        vault = self._vault(tmp_path)
        vault.write_page("concepts/index-finance", self._page("Finance", "finance"))
        vault.write_page("concepts/budget", self._page("Budget", "finance"))
        index = vault.root / "concepts/index-finance.md"
        assert "[[concepts/budget.md|Budget]]" in index.read_text()
        assert not (vault.root / "concepts/index-budget.md").exists()

    def test_creates_missing_category_index(self, tmp_path):
        vault = self._vault(tmp_path)
        vault.write_page("concepts/compiler", self._page("Compiler", "infrastructure"))
        index = vault.root / "concepts/index-infrastructure.md"
        assert index.exists()
        assert "[[concepts/compiler.md|Compiler]]" in index.read_text()

    def test_body_links_do_not_cross_classify_pages(self, tmp_path):
        vault = self._vault(tmp_path)
        vault.write_page("concepts/finance", self._page("Finance", "finance"))
        vault.write_page("concepts/budget", self._page("Budget", "finance"))
        vault.write_page(
            "concepts/unrelated",
            self._page("Unrelated", "operations")
            + "See the finance page: [[concepts/finance.md|Finance]].\n",
        )
        index = vault.root / "concepts/index-finance.md"
        text = index.read_text()
        assert "[[concepts/budget.md|Budget]]" in text
        assert "[[concepts/unrelated.md|Unrelated]]" not in text

    def test_creates_recurring_tag_hub(self, tmp_path):
        vault = self._vault(tmp_path)
        for name, tag in [("alpha-one", "alpha"), ("alpha-two", "alpha"), ("other", "beta")]:
            vault.write_page(f"concepts/{name}", self._page(name, tag))
        result = vault.ensure_tag_category_indexes()
        assert result["created_count"] == 1
        hub = vault.root / "concepts/index-alpha.md"
        assert hub.exists()
        vault.rebuild_category_indexes()
        text = hub.read_text()
        assert "[[concepts/alpha-one.md|alpha-one]]" in text
        assert "[[concepts/alpha-two.md|alpha-two]]" in text
        assert "[[concepts/other.md|other]]" not in text

    def test_category_index_failure_does_not_fail_page_write(self, tmp_path, monkeypatch):
        vault = self._vault(tmp_path)
        monkeypatch.setattr(vault, "_link_category_index", lambda _page: (_ for _ in ()).throw(OSError("boom")))
        result = vault.write_page("concepts/resilient", self._page("Resilient", "reliability"))
        assert result["status"] == "created"
        assert (vault.root / "concepts/resilient.md").exists()

    def test_root_index_is_not_used_as_category_index(self, tmp_path):
        vault = self._vault(tmp_path)
        vault.write_page("concepts/reliability", self._page("Reliability", "reliability"))
        category = vault.root / "concepts/index-reliability.md"
        assert category.exists()
        assert "[[concepts/reliability.md|Reliability]]" in category.read_text()
        assert category != vault.index_path
        assert "[[concepts/index-reliability.md|Reliability Index]]" in vault.index_path.read_text()

    def test_category_linking_is_idempotent(self, tmp_path):
        vault = self._vault(tmp_path)
        content = self._page("Stable", "operations")
        vault.write_page("concepts/stable", content)
        vault.write_page("concepts/stable", content)
        index = vault.root / "concepts/index-operations.md"
        assert index.read_text().count("[[concepts/stable.md|Stable]]") == 1
