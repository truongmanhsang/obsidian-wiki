#!/usr/bin/env python3
"""Trang thai wiki backlog - chay bat ky luc nao: wiki-backlog-status"""
import json, os, subprocess, sys, time
from pathlib import Path
from datetime import datetime

VAULT = os.environ.get(
    "OBSIDIAN_VAULT_PATH",
    str(Path.home() / "Library/Mobile Documents/iCloud~md~obsidian/Documents/agent-vault"),
)
STATE = os.environ.get("WIKI_BACKLOG_STATE", str(Path.home() / ".hermes/cache/wiki-backlog-state.json"))
PID_HINT = "wiki_backlog_extract"
TOTAL = 919

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
eta_h = (TOTAL - done) * avg / 3600 if avg else 0

# wiki page count
try:
    sys.path.insert(0, os.path.expanduser("~/.hermes/plugins/obsidianwiki"))
    from wiki import WikiVault
    vault = WikiVault(VAULT)
    pages = vault.load_pages()
    curated = len([p for p in pages if p["ptype"] != "source"])
except Exception:
    curated = "?"

bar_len = 24
filled = int(bar_len * done / TOTAL)
bar = "#" * filled + "-" * (bar_len - filled)

print(f"WIKI BACKLOG STATUS  ({datetime.now():%d/%m %H:%M})")
print(f"[{bar}] {done}/{TOTAL} ({100*done/TOTAL:.1f}%)")
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
if not pid and done < TOTAL:
    print("\nResume bang lenh:")
    print("  ~/.hermes/hermes-agent/venv/bin/python ~/.hermes/plugins/obsidianwiki/scripts/wiki_backlog_extract.py &")
