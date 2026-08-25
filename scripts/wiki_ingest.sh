#!/usr/bin/env bash
# wiki_ingest.sh - full session-to-wiki pipeline for agent-vault
#
# Submit an ingest job to the central memory server. The server owns capture,
# extraction, queueing, locking, and all vault writes.
#
# Designed for the cron job "wiki-ingest". Exit code 0 always unless
# something catastrophic happens; the JSON report is the output contract.

set -u
SCRIPTS="$(cd "$(dirname "$0")" && pwd)"
exec python3 "$SCRIPTS/wiki_ingest_submit.py" "$@"
