#!/usr/bin/env python3
"""Trang thai wiki backlog - chay bat ky luc nao: wiki-backlog-status"""
import json, os, subprocess, sys, time
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from obsidian_memory_core.config import DEFAULT_VAULT_PATH

VAULT = os.environ.get(
    "OBSIDIAN_VAULT_PATH",
    DEFAULT_VAULT_PATH,
)
STATE = os.environ.get("WIKI_BACKLOG_STATE", str(Path.home() / "Library/Application Support/obsidian-memory/wiki-backlog-state.json"))
PID_HINT = "wiki_backlog_extract"


st = {}
if os.path.exists(STATE):
    st = json.load(open(STATE))
done = len(st.get("done", []))
failed = st.get("failed", [])

# runner alive?
ps = subprocess.run(["ps", "aux"], capture_output=True, text=True).stdout
alive = [l for l in ps.splitlines() if PID_HINT in l and "grep" not in l]
pid = alive[0].split()[1] if alive else None

# uptime via etime (macOS: ps -o etime= -p PID)
uptime_min = 0
if pid:
    r = subprocess.run(["ps", "-o", "etime=", "-p", pid], capture_output=True, text=True)
    v = r.stdout.strip()
    if ":" in v:
        parts = [int(x) for x in v.split(":")]
        secs = parts[-1] + parts[-2] * 60 + (parts[-3] * 3600 if len(parts) > 2 else 0)
        uptime_min = secs / 60

started = st.get("started")
avg = ((time.time() - started) / max(done, 1)) if started and done else 0
total = max(done, 1)

# wiki page count
try:
    sys.path.insert(0, os.path.expanduser("~/.hermes/plugins/obsidianwiki"))
    from obsidian_memory_core.wiki import WikiVault
    vault = WikiVault(VAULT)
    pages = vault.load_pages()
    curated = len([p for p in pages if p["ptype"] != "source"])
    total = max(len(list(vault.root.glob("sources/sessions/**/*.md"))), done)
except Exception:
    curated = "?"
    total = max(done, 1)

eta_h = max(total - done, 0) * avg / 3600 if avg else 0

bar_len = 24
filled = int(bar_len * done / max(total, 1))
bar = "#" * filled + "-" * (bar_len - filled)

print(f"WIKI BACKLOG STATUS  ({datetime.now():%d/%m %H:%M})")
print(f"[{bar}] {done}/{total} ({100*done/max(total, 1):.1f}%)")
status = f"RUNNING (pid {pid}, up {uptime_min:.0f}p)" if pid else "STOPPED"
print(f"runner : {status}")
print(f"pace   : {avg:.0f}s/source | failed: {len(failed)}")
print(f"ETA    : ~{eta_h:.0f}h ({eta_h/24:.1f} ngay)" if avg else "")
print(f"wiki   : {curated} curated pages")
if failed:
    print("FAILED:")
    for f in failed[:5]:
        print(f"  - {f['rel'][:70]}")

# resume hint when stopped and work remains
if not pid and done < total:
    print("\nResume bang lenh:")
    print("  ~/.hermes/hermes-agent/venv/bin/python ~/.hermes/plugins/obsidianwiki/scripts/wiki_backlog_extract.py &")
