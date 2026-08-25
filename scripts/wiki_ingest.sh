#!/usr/bin/env bash
# wiki_ingest.sh - full session-to-wiki pipeline for agent-vault
#
# Step 1: capture uncaptured Hermes sessions into sources/sessions/
# Step 2: extract durable knowledge via LLM and merge into wiki pages
#
# Designed for the cron job "wiki-ingest". Exit code 0 always unless
# something catastrophic happens; the JSON report is the output contract.

set -u
SCRIPTS="$(cd "$(dirname "$0")" && pwd)"

echo "== STEP 1: capture sessions =="
python3 "$SCRIPTS/wiki_session_capture.py" --min-chars 300

echo ""
echo "== STEP 2: extract knowledge (apply) =="
python3 "$SCRIPTS/wiki_session_extract.py" --apply
