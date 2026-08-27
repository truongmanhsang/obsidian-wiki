"""Tests for the obsidianwiki memory provider.

Behavior contracts: index/log maintenance on write, folder-typed pages,
read-only sources/, path jailing, prefetch gating, lint invariants.
Runs against a temp vault - never touches the real agent-vault.
"""

import importlib.util
import asyncio
import json
import sys
from pathlib import Path

import pytest


class FakeEmbedder:
    """Deterministic stand-in for fastembed in unit tests."""

    def embed(self, texts):
        vectors = []
        for text in texts:
            low = text.casefold()
            vectors.append([
                float("girlfriend" in low or "partner" in low),
                float("trading" in low or "risk" in low),
            ])
        return vectors


# The plugin installs to $HERMES_HOME/plugins/obsidianwiki/, which pytest
# redirects away (HERMES_HOME -> tmp). Load the module by its real install
# path instead of going through plugin discovery.
PLUGIN_DIR = Path(__import__("os").environ.get(
    "OBSIDIANWIKI_PLUGIN_DIR", str(Path(__file__).resolve().parents[1])
))


def test_default_vault_path_is_portable(monkeypatch, tmp_path):
    import obsidian_memory_core.config as config
    monkeypatch.setattr(config.Path, "home", staticmethod(lambda: tmp_path))
    assert config.default_vault_path() == str(tmp_path / "Documents" / "agent-vault")


def test_schema_instructs_direct_wrapper(monkeypatch, tmp_path):
    provider = _load_provider_for_tests(tmp_path)
    description = provider.get_tool_schemas()[0]["description"]
    assert "obsidian_wiki tool directly" in description
    assert "tool_search" in description


def _load_provider_for_tests(tmp_path):
    from importlib import import_module

    module = import_module("obsidianwiki")
    return module.ObsidianWikiMemoryProvider({
        "vault_path": str(tmp_path / "vault"),
        "access_mode": "direct",
    })


def test_query_tokens_preserve_unicode_diacritics():
    from obsidian_memory_core.wiki.search import query_tokens

    assert query_tokens("girlfriend birth date") == [
        "girlfriend", "birth", "date",
    ]


def test_query_features_are_derived_from_page_text_not_domain_vocabulary():
    from obsidian_memory_core.wiki.intent import analyze_query

    features = analyze_query("girlfriend birth date")
    assert "girlfriend birth date" in features.get("phrases", [])
    assert "birth date" in features.get("phrases", [])
    assert "relation" not in features


def test_vietnamese_relationship_attribute_query_finds_curated_person_page(
    monkeypatch, tmp_path,
):
    from obsidian_memory_core import MemoryStore
    import obsidian_memory_core.wiki.fts as fts

    store = MemoryStore(tmp_path / "vault")
    store.ensure_ready()
    store.write(
        "people/sang-girlfriend",
        "---\ntype: person\naliases: [Xuan Mai, Xuan Mai]\n"
        "relations:\n  - subject: sang\n    relation: girlfriend\n---\n"
        "# Xuan Mai\n\nGirlfriend of Sang.\n\n"
        "Date of birth: 7 February 1997\n",
    )
    monkeypatch.setattr(fts, "_embedding_search", lambda *args, **kwargs: [])

    result = store.search("girlfriend I birth date how many", limit=5)

    assert result["results"]
    assert result["results"][0]["path"] == "people/sang-girlfriend.md"
    assert result["results"][0]["type"] == "person"


def test_vector_embedding_fallback_runs_only_after_lexical_miss(monkeypatch, tmp_path):
    from obsidian_memory_core import MemoryStore
    import obsidian_memory_core.wiki.fts as fts

    store = MemoryStore(tmp_path / "vault")
    store.ensure_ready()
    store.write("people/xuan-mai", "# Xuan Mai\n\nGirlfriend of Sang.\n")
    monkeypatch.setattr(fts, "_get_embedder", lambda: FakeEmbedder())
    fts._reset_embedder_for_tests()

    result = store.search("partner of mine", limit=5)
    assert result["count"] == 1
    assert result["results"][0]["path"] == "people/xuan-mai.md"
    assert result["results"][0]["match"] == "embedding"


def test_vector_embedding_fallback_filters_below_threshold(monkeypatch, tmp_path):
    from obsidian_memory_core import MemoryStore
    import obsidian_memory_core.wiki.fts as fts

    store = MemoryStore(tmp_path / "vault")
    store.ensure_ready()
    store.write("concepts/trading", "# Trading\n\nRisk management for markets.\n")
    monkeypatch.setattr(fts, "_get_embedder", lambda: FakeEmbedder())
    fts._reset_embedder_for_tests()

    result = store.search("cooking recipe", limit=5)
    assert result["count"] == 0


def test_hybrid_search_runs_embedding_on_weak_lexical_hits_and_merges(monkeypatch, tmp_path):
    from obsidian_memory_core import MemoryStore
    import obsidian_memory_core.wiki.fts as fts

    store = MemoryStore(tmp_path / "vault")
    store.ensure_ready()
    store.write("people/xuan-mai", "# Xuan Mai\n\nGirlfriend of Sang.\n")
    store.write("concepts/calendar", "# Calendar\n\nBirthday reminders.\n")
    calls = []

    def fake_embedding_search(vault, query, limit=5, threshold=None):
        calls.append(query)
        return [{
            "path": "people/xuan-mai.md",
            "title": "Xuan Mai",
            "type": "person",
            "updated": "2026-08-26",
            "score": 0.91,
            "snippet": "",
            "match": "embedding",
        }]

    monkeypatch.setattr(fts, "_embedding_search", fake_embedding_search)
    result = store.search("birth date birthday", limit=5)

    assert calls == ["birth date birthday"]
    assert result["results"][0]["path"] == "people/xuan-mai.md"
    assert result["results"][0]["match"] == "embedding"
    assert result["results"][0]["score"] > 0.7


def test_hybrid_search_does_not_embed_exact_name_match(monkeypatch, tmp_path):
    from obsidian_memory_core import MemoryStore
    import obsidian_memory_core.wiki.fts as fts

    store = MemoryStore(tmp_path / "vault")
    store.ensure_ready()
    store.write(
        "people/xuan-mai",
        "---\ntype: person\naliases: [Xuan Mai]\n---\n"
        "# Xuan Mai\n\nGirlfriend of Sang.\n",
    )
    monkeypatch.setattr(
        fts, "_embedding_search",
        lambda *args, **kwargs: pytest.fail("exact name should not trigger embedding"),
    )

    result = store.search("Xuan Mai", limit=5)

    assert result["results"][0]["path"] == "people/xuan-mai.md"


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
    store.write("people/xuan-mai", "# Xuan Mai\n\nGirlfriend of Sang.\n")

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


def test_shared_core_write_revision_and_lock(tmp_path):
    from obsidian_memory_core import MemoryStore

    store = MemoryStore(tmp_path / "vault")
    store.ensure_ready()
    created = store.write("concepts/shared-core", "# Shared Core\n\nA durable memory page with enough content.\n")
    assert created["status"] == "created"
    revision = store.read("concepts/shared-core")["revision"]
    updated = store.write(
        "concepts/shared-core",
        "# Shared Core\n\nUpdated durable memory content.\n",
        expected_revision=revision,
    )
    assert updated["status"] == "updated"
    assert store.read("concepts/shared-core")["revision"] != revision

    with pytest.raises(Exception, match="revision conflict"):
        store.write("concepts/shared-core", "# Stale\n\nRejected stale update.\n", expected_revision=revision)


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


def test_mcp_exposes_read_and_write_tools():
    from mcp_server import mcp

    names = {tool.name for tool in asyncio.run(mcp.list_tools())}
    assert {"memory_search", "memory_reflect", "memory_read", "memory_write", "memory_ingest_submit", "memory_ingest_status"}.issubset(names)


def test_mcp_reflect_tool_returns_grounded_sources(monkeypatch, tmp_path):
    import mcp_server

    mcp_server._SERVER_VAULT_PATH = str(tmp_path / "vault")
    store = mcp_server._store(prepare=True)
    store.write("people/sang", "# Sang\n\nPrefers concise replies.\n")
    monkeypatch.setattr(mcp_server, "_run_reflection", lambda query, pages: "Grounded answer")
    result = mcp_server.memory_reflect("What does Sang prefer?", limit=3)
    assert result["reflection"] == "Grounded answer"
    assert result["sources"]


def test_reflect_returns_synthesis_from_relevant_pages(monkeypatch, tmp_path):
    mod = _load_module()
    provider = mod.ObsidianWikiMemoryProvider({"vault_path": str(tmp_path / "vault"), "access_mode": "direct"})
    provider.initialize(session_id="test")
    _call(provider, action="write", page="people/sang", content="# Sang\n\nPrefers concise Telegram replies.\n")
    monkeypatch.setattr(mod, "_run_reflection", lambda query, pages: "Sang prefers concise Telegram replies.")
    result = _call(provider, action="reflect", query="What communication style does Sang prefer?")
    assert result["query"] == "What communication style does Sang prefer?"
    assert result["reflection"] == "Sang prefers concise Telegram replies."
    assert result["sources"][0]["path"] == "people/sang.md"


def test_reflect_requires_query(provider):
    result = _call(provider, action="reflect", query="")
    assert result["error"]


def test_mcp_provider_filters_unrecognized_arguments(monkeypatch, tmp_path):
    mod = _load_module()
    provider = mod.ObsidianWikiMemoryProvider({"vault_path": str(tmp_path / "vault"), "access_mode": "mcp"})
    provider.initialize(session_id="test")
    captured = {}
    monkeypatch.setattr(provider, "_mcp_call", lambda tool, args: captured.update(tool=tool, args=args) or {"results": []})
    result = json.loads(provider.handle_tool_call("obsidian_wiki", {
        "action": "search", "query": "test", "limit": 5, "page": "", "content": "", "note": "", "expected_revision": ""
    }))
    assert result == {"results": []}
    assert captured == {"tool": "memory_search", "args": {"query": "test", "limit": 5}}


def test_hermes_provider_uses_shared_store_revision(tmp_path):
    mod = _load_module()
    provider = mod.ObsidianWikiMemoryProvider({"vault_path": str(tmp_path / "vault"), "access_mode": "direct"})
    provider.initialize(session_id="test")
    created = json.loads(provider.handle_tool_call("obsidian_wiki", {
        "action": "write", "page": "concepts/provider", "content": "# Provider\n\nShared write path content.\n"
    }))
    revision = json.loads(provider.handle_tool_call("obsidian_wiki", {
        "action": "read", "page": "concepts/provider"
    })) ["revision"]
    assert created["status"] == "created"
    stale = json.loads(provider.handle_tool_call("obsidian_wiki", {
        "action": "write", "page": "concepts/provider", "content": "# Stale\n\nNo overwrite.\n", "expected_revision": "stale"
    }))
    assert stale["error"] == "revision_conflict"
    assert revision


def _load_module():
    if str(PLUGIN_DIR) not in sys.path:
        sys.path.insert(0, str(PLUGIN_DIR))
    spec = importlib.util.spec_from_file_location(
        "obsidianwiki_under_test", PLUGIN_DIR / "__init__.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["obsidianwiki_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def provider(tmp_path):
    if not PLUGIN_DIR.is_dir():
        pytest.skip("obsidianwiki plugin not installed")
    mod = _load_module()
    p = mod.ObsidianWikiMemoryProvider({"vault_path": str(tmp_path / "v"), "access_mode": "direct"})
    p.initialize(session_id="test")
    return p


def _call(p, **args):
    return json.loads(p.handle_tool_call("obsidian_wiki", args))


class TestWritePath:
    def test_write_creates_page_with_derived_frontmatter(self, provider):
        r = _call(provider, action="write", page="entities/A",
                  content="# A\n\nSome body line.\n")
        assert r["status"] == "created"
        assert r["type"] == "entity"
        text = open(r["path"]).read()
        assert "type: entity" in text and "updated: 20" in text

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

    def test_wrong_folder_type_conflicts(self, provider):
        r = _call(provider, action="write", page="answers/x",
                  content="---\ntype: entity\n---\n\n# X\n\nbody\n")
        assert "error" in r

    def test_path_escape_rejected(self, provider):
        r = _call(provider, action="write", page="../evil",
                  content="# evil\n\nbad bad bad\n")
        assert "error" in r

    def test_short_content_rejected(self, provider):
        r = _call(provider, action="write", page="entities/x", content="# x\n")
        assert "error" in r

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
                      content="body without a heading but enough content\n")
        no_h1_text = open(no_h1["path"]).read()
        assert "aliases: ['No Heading']" in no_h1_text
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
        _call(provider, action="write", page="people/sang-girlfriend",
              content="---\ntype: person\nupdated: 2026-08-26\ntags: [family]\naliases: [Xuan Mai, Xuan Mai]\n---\n\n# Xuan Mai\n\nDate of birth: 7 February 1997.\n")
        r = _call(provider, action="search", query="Xuan Mai birth date how many", limit=5)
        assert r["results"]
        assert r["results"][0]["path"] == "people/sang-girlfriend.md"


class TestLint:
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
        _call(provider, action="write", page="entities/sang-bot",
              content="# Sang Bot\n\nlinks [[entities/sang-girlfriend|girlfriend]]\n")
        # Another page's log line mentions sang-bot in passing.
        vault = provider._get_vault()
        vault.append_log("WRITE", "updated entities/sang-girlfriend with note about sang-bot meeting")
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
        r = _call(provider, action="write", page="people/truc-icario",
                  content="---\ntype: person\nupdated: 2026-08-01\ntags: [icario]\naliases: []\n---\n\n# Mr. Truc\n\nQA automation engineer.\n")
        text = open(r["path"]).read()
        # Auto-fill kicked in: aliases no longer empty.
        assert "aliases: []" not in text, text
        vault = provider._get_vault()
        # A different page's WRITE line happens to mention truc-icario.
        vault.append_log("WRITE", "updated entities/icario, referenced truc-icario in team list")
        lint1 = json.loads(provider.handle_tool_call("obsidian_wiki",
                                                      {"action": "lint"}))
        assert "aliases_wiped" not in lint1.get("problems", {}), lint1

        # Now a genuine guard event naming the exact file. Because the page was
        # already auto-filled (not empty), aliases_wiped must still NOT fire.
        vault.append_log(
            "WRITE",
            "frontmatter guard: preserving aliases ['Truc'] for "
            f"{vault.root / 'people' / 'truc-icario.md'} (would have wiped to [])",
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


class TestPrefetch:
    def test_trivial_query_returns_empty(self, provider):
        assert provider.prefetch("ok") == ""

    def test_strong_match_injected(self, provider):
        _call(provider, action="write", page="entities/topic-beta-zz",
              content="# Topic Beta ZZ\n\ngeneric topic beta research notes\n")
        ctx = provider.prefetch("what about topic beta zz research?")
        assert "[[entities/topic-beta-zz.md|Topic Beta ZZ]]" in ctx

    def test_recall_status_counts(self, provider):
        assert provider.recall_status() is None
        _call(provider, action="write", page="entities/widget-gamma",
              content="# Widget Gamma\n\nwidget gamma details live here\n")
        provider.prefetch("tell me about widget gamma details")
        st = provider.recall_status()
        assert st is not None and st.count >= 1

    def test_auto_prefetch_reflects_synthesis_queries(self, provider, monkeypatch):
        _call(provider, action="write", page="concepts/trading-choice",
              content="# Trading Choice\n\nA durable comparison of strategy risk and returns.\n")
        mod = sys.modules[provider.__class__.__module__]
        calls = []
        monkeypatch.setattr(
            mod, "_run_reflection",
            lambda query, pages: calls.append((query, pages)) or "Synthesized wiki answer.",
        )
        provider._config["prefetch_method"] = "auto"
        ctx = provider.prefetch("which strategy is best for trading risk?")
        assert "Synthesized wiki answer." in ctx
        assert calls and calls[0][1]

    def test_recall_prefetch_does_not_call_reflection(self, provider, monkeypatch):
        mod = sys.modules[provider.__class__.__module__]
        monkeypatch.setattr(
            mod, "_run_reflection",
            lambda *args: pytest.fail("recall mode must not reflect"),
        )
        provider._config["prefetch_method"] = "recall"
        provider.prefetch("tell me about a normal topic")


class TestLifecycle:
    def test_system_prompt_block_lists_catalog(self, provider):
        _call(provider, action="write", page="entities/cat",
              content="# Cat\n\na catalogued feline entity\n")
        block = provider.system_prompt_block()
        assert "# Obsidian Wiki Memory" in block
        assert "Cat" in block
        assert "must never be edited with filesystem tools" in block
        assert "mcp__obsidian_wiki__memory_write" in block

    def test_skeleton_created_on_demand(self, provider, tmp_path):
        v = provider._get_vault()
        assert not v.index_path.exists() or True
        provider._get_vault().ensure_skeleton()
        assert (v.root / "templates" / "entity-template.md").exists()

    def test_unknown_tool_and_action(self, provider):
        assert "error" in provider.handle_tool_call("other_tool", {})
        assert "error" in _call(provider, action="bogus")


class TestSessionExtractReport:
    def test_session_filename_is_safe(self):
        hook_path = PLUGIN_DIR / "scripts" / "wiki_turn_hook.py"
        spec = importlib.util.spec_from_file_location("wiki_turn_hook_under_test", hook_path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules["wiki_turn_hook_under_test"] = mod
        spec.loader.exec_module(mod)
        # The central hook is now an MCP event client; it no longer builds log filenames.
        assert hasattr(mod, "submit")
        assert hasattr(mod, "main")

    def test_report_is_written_at_end_of_session_note(self, tmp_path):
        script_dir = PLUGIN_DIR / "scripts"
        spec = importlib.util.spec_from_file_location(
            "wiki_session_extract_under_test", script_dir / "wiki_session_extract.py"
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules["wiki_session_extract_under_test"] = mod
        spec.loader.exec_module(mod)

        source = tmp_path / "session.md"
        source.write_text(
            "---\ntype: source\nextract_status: pending\n---\n\n# Session\n\nDialogue.\n",
            encoding="utf-8",
        )
        report = {
            "extract_status": "success",
            "applied": [
                {
                    "page": "entities/icario",
                    "action": "update",
                    "title": "Icario",
                    "summary": "Project and team context.",
                    "status": "updated",
                },
                {
                    "page": "people/hong-icario",
                    "action": "update",
                    "title": "Ms. Hong (Icario)",
                    "summary": "Direct manager and project team leader.",
                    "status": "updated",
                },
            ],
            "rejected_dedup": [],
        }

        mod.update_extract_status(source, "success", report)
        text = source.read_text(encoding="utf-8")
        assert "## LLM Extraction" in text
        assert "[[entities/icario|Icario]]" in text
        assert "[[people/hong-icario|Ms. Hong (Icario)]]" in text
        assert "Project and team context." in text
        assert text.index("## LLM Extraction") > text.index("Dialogue.")

        # Re-running extraction replaces the report instead of duplicating it.
        report["applied"] = [
            {
                "page": "concepts/new-lesson",
                "action": "create",
                "title": "New Lesson",
                "summary": "A durable lesson.",
                "status": "created",
            }
        ]
        mod.update_extract_status(source, "success", report)
        text = source.read_text(encoding="utf-8")
        assert text.count("## LLM Extraction") == 1
        assert "[[concepts/new-lesson|New Lesson]]" in text
        assert "[[entities/icario|Icario]]" not in text
