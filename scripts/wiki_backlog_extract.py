#!/usr/bin/env python3
"""Backlog extractor: mines ALL un-extracted sources/sessions transcripts.

Runs wiki_session_extract.py per source (LLM proposes durable facts ->
dedup -> apply into curated pages), stamps sources as extracted, and
tracks progress in /tmp/wiki-backlog-state.json so it resumes cleanly.

Designed for long unattended runs: one source at a time, retry x3,
never aborts on a single bad source.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT))
from obsidian_memory_core.wiki import WikiVault  # noqa: E402
from obsidian_memory_core import MemoryStore  # noqa: E402
from obsidian_memory_core.config import DEFAULT_VAULT_PATH  # noqa: E402

VAULT = Path(
    os.environ.get(
        "OBSIDIAN_VAULT_PATH",
        DEFAULT_VAULT_PATH,
    )
)
STATE = Path(os.environ.get("WIKI_BACKLOG_STATE", str(Path.home() / "Library/Application Support/obsidian-memory/wiki-backlog-state.json")))
SCRIPT = str(Path(__file__).with_name("wiki_session_extract.py"))
HERMES_PY = os.environ.get("HERMES_PYTHON", sys.executable)
BATCH_DELAY = 5  # seconds between sources


def load_state() -> dict:
    if STATE.exists():
        return json.loads(STATE.read_text())
    return {"done": [], "failed": [], "started": None}


def save_state(st: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_name(f".{STATE.name}.tmp-{os.getpid()}")
    tmp.write_text(json.dumps(st, indent=1), encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(STATE)


def stamp_extracted(path: Path, status: str) -> None:
    text = path.read_text(encoding="utf-8")
    m = text.split("---", 2)
    if len(m) < 3:
        return
    from datetime import date
    fm = m[1]
    if re.search(r"(?m)^extract_status:", fm):
        fm = re.sub(r"(?m)^extract_status:.*$", f"extract_status: {status}", fm, count=1)
    else:
        fm += f"\nextract_status: {status}"
    if status in {"success", "skip"} and not re.search(r"(?m)^extracted:", fm):
        fm += f"\nextracted: {date.today().isoformat()}"
    path.write_text(f"---{fm}\n---{m[2]}", encoding="utf-8")
    written_fm = path.read_text(encoding="utf-8").split("---", 2)[1]
    if not re.search(rf"(?m)^extract_status:\s*{re.escape(status)}\s*$", written_fm):
        raise RuntimeError(f"failed to write extract_status={status} for {path}")


import re  # noqa: E402


def main() -> int:
    store = MemoryStore(str(VAULT))
    vault = store.vault
    st = load_state()
    if st.get("started") is None:
        st["started"] = time.time()

    pending = []
    for p in sorted(vault.root.rglob("sources/sessions/**/*.md")):
        meta, _ = vault.parse_frontmatter(p.read_text(encoding="utf-8"))
        rel = str(p.relative_to(vault.root))
        # Cron sessions are operational noise and are excluded from memory
        # ingestion even if an older capture created the source file.
        if p.stem.startswith("cron_"):
            continue
        if not meta.get("extracted") and rel not in st["done"]:
            pending.append((p, rel))

    print(f"backlog: {len(pending)} sources to mine", flush=True)
    ok = fail = 0
    for i, (p, rel) in enumerate(pending):
        # skip tiny transcripts (<200 chars body = nothing to learn)
        size = p.stat().st_size
        if size < 400:
            st["done"].append(rel)
            store.update_ingest_status(rel, "skip")
            continue
        rel_arg = str(p.relative_to(vault.root / "sources/sessions"))
        try:
            r = subprocess.run(
                [HERMES_PY, SCRIPT, "--sessions", rel_arg, "--apply"],
                capture_output=True, text=True, timeout=600,
            )
            if r.returncode == 0 and r.stdout.strip():
                try:
                    data = json.loads(r.stdout)
                    applied = data.get("applied") or data.get("applied_proposals") or []
                    n_pages = len(applied) if isinstance(applied, list) else 0
                    extract_status = data.get("extract_status") or ("success" if n_pages else "skip")
                    health = data.get("wiki_health") or {}
                    clean = health.get("clean")
                except json.JSONDecodeError:
                    n_pages, clean, extract_status = 0, None, "fail"
                store.update_ingest_status(rel, extract_status)
                st["done"].append(rel)
                ok += 1
                print(
                    f"[{i+1}/{len(pending)}] {rel}: +{n_pages} pages "
                    f"(lint_clean={clean})",
                    flush=True,
                )
            else:
                raise RuntimeError(
                    (r.stderr or r.stdout or "no output")[-160:]
                )
        except Exception as e:  # noqa: BLE001
            store.update_ingest_status(rel, "fail")
            st["failed"].append({"rel": rel, "err": str(e)[:150]})
            fail += 1
            print(f"[{i+1}/{len(pending)}] FAILED {rel}: {str(e)[:100]}", flush=True)

        st["last"] = rel
        save_state(st)
        time.sleep(BATCH_DELAY)

    print(f"backlog COMPLETE: {ok} mined, {fail} failed", flush=True)
    save_state(st)
    return 0


if __name__ == "__main__":
    sys.exit(main())
