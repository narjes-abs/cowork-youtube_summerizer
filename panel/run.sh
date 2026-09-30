#!/usr/bin/env bash
# Start the Learning Panel. First checks everything it needs (and installs what is missing), then starts it.
#   panel/run.sh [localhost:number]   set up if needed, then start; the optional value picks the port (default localhost:8000)
#   PANEL_SKIP_SETUP=1 panel/run.sh   start without the setup check
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
VENV="$HERE/../.claude/skills/yt-summary/.venv"
if [ "${PANEL_SKIP_SETUP:-0}" != "1" ]; then
  "$HERE/setup.sh" --quiet || { echo; echo "Setup found problems (above). The panel was not started."; exit 1; }
fi
exec "$VENV/bin/python" -W ignore "$HERE/server.py" "$@"
