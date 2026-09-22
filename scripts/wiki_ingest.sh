#!/usr/bin/env bash
# wiki_ingest.sh - full session-to-wiki pipeline for agent-vault
#
# Submit an ingest job to the plugin-owned worker. Capture/extraction run in
# the Hermes Python environment; MCP/web only monitor status.
#
# Designed for the cron job "wiki-ingest". Exit code 0 always unless
# something catastrophic happens; the JSON report is the output contract.

set -u
SCRIPTS="$(cd "$(dirname "$0")" && pwd)"
PYTHON="${HERMES_PYTHON:-python3}"
exec "$PYTHON" "$SCRIPTS/wiki_ingest_submit.py" "$@"
