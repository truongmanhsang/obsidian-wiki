"""Tests for the obsidianwiki memory provider.

Behavior contracts: index/log maintenance on write, folder-typed pages,
read-only sources/, path jailing, prefetch gating, lint invariants.
Runs against a temp vault - never touches the real agent-vault.
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest


# The plugin installs to $HERMES_HOME/plugins/obsidianwiki/, which pytest
# redirects away (HERMES_HOME -> tmp). Load the module by its real install
# path instead of going through plugin discovery.
PLUGIN_DIR = Path.home() / ".hermes" / "plugins" / "obsidianwiki"


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
    p = mod.ObsidianWikiMemoryProvider({"vault_path": str(tmp_path / "v")})
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
        _call(provider, action="write", page="entities/a1",
              content="# A1\n\nsecond body\n")
        r = _call(provider, action="read", page="entities/a1")
        assert r["content"].count("updated: 20") == 1
        assert "second body" in r["content"]


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


class TestLifecycle:
    def test_system_prompt_block_lists_catalog(self, provider):
        _call(provider, action="write", page="entities/cat",
              content="# Cat\n\na catalogued feline entity\n")
        block = provider.system_prompt_block()
        assert "# Obsidian Wiki Memory" in block
        assert "Cat" in block

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
        assert "/" not in mod.safe_session_filename("../../outside/x")
        assert mod.safe_session_filename("") == "adhoc"

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
                    "title": "Chị Hồng (Icario)",
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
        assert "[[people/hong-icario|Chị Hồng (Icario)]]" in text
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
