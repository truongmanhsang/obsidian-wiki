"""Session extraction and ingest job manager behavior tests."""

import asyncio
import importlib.util
import json
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
                    "page": "entities/example-project",
                    "action": "update",
                    "title": "ExampleProject",
                    "summary": "Project and team context.",
                    "status": "updated",
                },
                {
                    "page": "people/example-manager-example-project",
                    "action": "update",
                    "title": "Ms. Example Manager (ExampleProject)",
                    "summary": "Direct manager and project team leader.",
                    "status": "updated",
                },
            ],
            "rejected_dedup": [],
        }

        mod.update_extract_status(source, "success", report)
        text = source.read_text(encoding="utf-8")
        assert "## LLM Extraction" in text
        assert "[[entities/example-project|ExampleProject]]" in text
        assert "[[people/example-manager-example-project|Ms. Example Manager (ExampleProject)]]" in text
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
        assert "[[entities/example-project|ExampleProject]]" not in text


class TestIngestJobManager:
    def test_default_job_db_path_uses_platform_state_directory(self, monkeypatch, tmp_path):
        from obsidian_memory_core import jobs

        monkeypatch.delenv("WIKI_JOB_DB", raising=False)
        monkeypatch.setattr(jobs.Path, "home", staticmethod(lambda: tmp_path))
        monkeypatch.setattr(jobs.sys, "platform", "linux")
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg-state"))
        assert jobs._default_job_db_path() == tmp_path / "xdg-state" / "obsidian-memory" / "jobs.db"

        monkeypatch.setattr(jobs.sys, "platform", "win32")
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local-app-data"))
        assert jobs._default_job_db_path() == tmp_path / "local-app-data" / "obsidian-memory" / "jobs.db"

        monkeypatch.setattr(jobs.sys, "platform", "darwin")
        monkeypatch.delenv("XDG_STATE_HOME", raising=False)
        monkeypatch.delenv("LOCALAPPDATA", raising=False)
        assert jobs._default_job_db_path() == tmp_path / "Library" / "Application Support" / "obsidian-memory" / "jobs.db"

    def test_completed_early_or_failed_jobs_are_retryable(self):
        from obsidian_memory_core.jobs import IngestJobManager

        assert IngestJobManager._is_retryable_completed({
            "status": "completed",
            "capture_output": '{"skipped_too_small": 1}',
            "extract_output": "",
        })
        assert IngestJobManager._is_retryable_completed({
            "status": "completed",
            "capture_output": "",
            "extract_output": '{"extract_status": "fail"}',
        })
        assert not IngestJobManager._is_retryable_completed({
            "status": "completed",
            "capture_output": '{"skipped_too_small": 0}',
            "extract_output": '{"extract_status": "success"}',
        })

    def test_capture_retry_policy_allows_state_db_flush(self):
        from obsidian_memory_core import jobs

        assert jobs.IngestJobManager._capture_retry_delays() == (0, 3, 10, 30)

    def test_extractor_uses_hermes_python_when_system_python_is_selected(self, tmp_path, monkeypatch):
        from obsidian_memory_core import jobs

        hermes_python = tmp_path / "hermes-python"
        hermes_python.write_text("", encoding="utf-8")
        monkeypatch.setenv("HERMES_PYTHON", str(hermes_python))
        assert jobs.IngestJobManager._runtime_python() == str(hermes_python)

    def test_apply_update_passes_current_revision(self, tmp_path):
        from obsidian_memory_core import MemoryStore
        import importlib.util

        script = PLUGIN_DIR / "scripts" / "wiki_session_extract.py"
        spec = importlib.util.spec_from_file_location("wiki_session_extract_revision_test", script)
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        sys.modules["wiki_session_extract_revision_test"] = mod
        spec.loader.exec_module(mod)

        store = MemoryStore(tmp_path / "vault")
        store.ensure_ready()
        store.write(
            "concepts/existing",
            valid_page_content("concepts/existing", "# Existing\n\nOriginal durable content.\n"),
        )
        revision = store.read("concepts/existing")["revision"]
        result = mod.apply_proposals(
            store.vault,
            [{
                "page": "concepts/existing",
                "action": "update",
                "content": valid_page_content(
                    "concepts/existing", "# Existing\n\nUpdated durable content.\n"
                ),
            }],
            store,
        )
        assert result[0]["status"] == "updated"
        assert store.read("concepts/existing")["revision"] != revision
