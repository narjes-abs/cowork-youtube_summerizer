#!/usr/bin/env bash
# Learning Panel setup: checks everything the panel needs, installs what is missing, and reports.
#   panel/setup.sh            check, install what is missing, report
#   panel/setup.sh --check    only report; install nothing
#   panel/setup.sh --quiet    print only what needed attention (panel/run.sh uses this)
set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
VENV="${PANEL_VENV_DIR:-$ROOT/.claude/skills/yt-summary/.venv}"
REQ="${PANEL_REQUIREMENTS:-$ROOT/.claude/skills/yt-summary/requirements.txt}"
OLLAMA_URL="${OLLAMA_URL:-http://localhost:11434}"
DEFAULT_MODEL="qwen3.5:9b"
KEY_SERVICE="LearningPanel Anthropic API key"
MODE=install
QUIET=0
PROBLEMS=0
HEADER_SHOWN=0

for arg in "$@"; do
  case "$arg" in
    --check) MODE=check ;;
    --quiet) QUIET=1 ;;
    -h|--help) sed -n '2,6p' "$0"; exit 0 ;;
    *) echo "Unknown option: $arg (try --help)" >&2; exit 2 ;;
  esac
done

have() { command -v "$1" >/dev/null 2>&1; }

# line STATE LABEL DETAIL   (in quiet mode only lines that needed attention are shown)
line() {
  if [ "$QUIET" -eq 1 ] && [ "$1" = "ok" ]; then return 0; fi
  if [ "$HEADER_SHOWN" -eq 0 ]; then
    HEADER_SHOWN=1
    if [ "$MODE" = "check" ]; then echo "Learning Panel setup check (nothing will be installed):"; else echo "Learning Panel setup:"; fi
  fi
  printf '  %-10s %-24s %s\n' "$1" "$2" "$3"
}
problem() { PROBLEMS=$((PROBLEMS + 1)); line "$1" "$2" "$3"; }
show_and_run() { printf '    -> %s\n' "$*"; "$@"; }

# ---------- 1. Python 3.9+ ----------
python_ok() { have python3 && python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' >/dev/null 2>&1; }
PYTHON_READY=0
if python_ok; then
  line ok "Python" "$(python3 --version 2>&1)"; PYTHON_READY=1
elif [ "$MODE" = "check" ]; then
  problem MISSING "Python 3.9+" "install: brew install python@3.12 (needs Homebrew, https://brew.sh)"
elif have brew; then
  if show_and_run brew install python@3.12 && python_ok; then line installed "Python" "python@3.12 via Homebrew"; PYTHON_READY=1
  else problem FAILED "Python 3.9+" "brew install python@3.12 did not work; install Python 3.9+ from python.org"; fi
else
  problem FAILED "Python 3.9+" "install Homebrew (https://brew.sh) or Python from https://www.python.org/downloads/, then run this again"
fi

# ---------- 2. Private environment + Python library ----------
lib_ok() { [ -x "$VENV/bin/python" ] && "$VENV/bin/python" -c 'import youtube_transcript_api' >/dev/null 2>&1; }
if lib_ok; then
  line ok "Python library" "youtube-transcript-api"
elif [ "$MODE" = "check" ]; then
  problem MISSING "Python library" "will be installed into $VENV when you run without --check"
elif [ "$PYTHON_READY" -ne 1 ]; then
  problem FAILED "Python library" "needs Python 3.9+ first (see above)"
else
  if [ ! -x "$VENV/bin/python" ]; then show_and_run python3 -m venv "$VENV" || true; fi
  if [ -x "$VENV/bin/python" ] && show_and_run "$VENV/bin/python" -m pip install -q --disable-pip-version-check -r "$REQ" && lib_ok; then
    line installed "Python library" "youtube-transcript-api"
  else
    problem FAILED "Python library" "could not install; check your internet connection and run this again"
  fi
fi

# ---------- 3. Ollama installed ----------
if have ollama; then
  line ok "Ollama" "$(ollama --version 2>&1 | grep -i version | head -1)"
elif [ "$MODE" = "check" ]; then
  problem MISSING "Ollama" "install: brew install ollama, or download from https://ollama.com/download"
elif have brew; then
  if show_and_run brew install ollama && have ollama; then line installed "Ollama" "via Homebrew"
  else problem FAILED "Ollama" "brew install ollama did not work; download it from https://ollama.com/download"; fi
else
  problem FAILED "Ollama" "download and install it from https://ollama.com/download (or install Homebrew first), then run this again"
fi

# ---------- 4. Ollama running ----------
ollama_up() { curl -fsS --max-time 3 "$OLLAMA_URL/api/tags" >/dev/null 2>&1; }
OLLAMA_READY=0
if ! have ollama; then
  line skipped "Ollama running" "waiting for Ollama to be installed"
elif ollama_up; then
  line ok "Ollama running" "$OLLAMA_URL"; OLLAMA_READY=1
elif [ "$MODE" = "check" ]; then
  problem MISSING "Ollama running" "start it: ollama serve (or open the Ollama app)"
else
  printf '    -> ollama serve (in the background)\n'
  nohup ollama serve >"${TMPDIR:-/tmp}/ollama-serve.log" 2>&1 &
  i=0
  while [ "$i" -lt 40 ]; do ollama_up && break; sleep 0.5; i=$((i + 1)); done
  if ollama_up; then line started "Ollama running" "$OLLAMA_URL"; OLLAMA_READY=1
  else problem FAILED "Ollama running" "could not start it; open the Ollama app or run: ollama serve"; fi
fi

# ---------- 5. A local model ----------
installed_sizes() { curl -fsS --max-time 5 "$OLLAMA_URL/api/tags" 2>/dev/null | grep -o '"name": *"qwen3.5:[^"]*"' | sed 's/.*"qwen3.5:\([^"]*\)"/\1/'; }
levels() { # e.g. "available: Easy(2b) | not installed: Medium(9b), Hard(27b)"
  have_list=""; miss_list=""
  for pair in "Easy:2b" "Medium:9b" "Hard:27b"; do
    name="${pair%%:*}"; size="${pair##*:}"
    if installed_sizes | grep -qx "$size"; then have_list="$have_list${have_list:+, }$name($size)"
    else miss_list="$miss_list${miss_list:+, }$name($size)"; fi
  done
  if [ -n "$miss_list" ]; then echo "available: $have_list | not installed: $miss_list"; else echo "available: $have_list"; fi
}
if [ "$OLLAMA_READY" -ne 1 ]; then
  line skipped "Local model" "needs Ollama running first"
elif [ -n "$(installed_sizes)" ]; then
  line ok "Local model" "$(levels)"
elif [ "$MODE" = "check" ]; then
  problem MISSING "Local model" "install: ollama pull $DEFAULT_MODEL (about 6.6 GB)"
else
  echo "    -> downloading the default model (about 6.6 GB, this can take a while)"
  if show_and_run ollama pull "$DEFAULT_MODEL" && [ -n "$(installed_sizes)" ]; then line installed "Local model" "$DEFAULT_MODEL"
  else problem FAILED "Local model" "could not download $DEFAULT_MODEL; check your internet connection and run: ollama pull $DEFAULT_MODEL"; fi
fi

# ---------- 6. and 7. Slower, optional checks (skipped in quiet mode) ----------
if [ "$QUIET" -ne 1 ]; then
  if curl -fsSI --max-time 8 https://www.youtube.com >/dev/null 2>&1; then
    line ok "YouTube reachable" "captions can be downloaded"
  else
    line warning "YouTube reachable" "no connection to youtube.com; summaries need it (check your internet or VPN)"
  fi
  if [ "$(uname)" != "Darwin" ]; then
    line warning "API key storage" "the Keychain is macOS-only; cloud models will not work here"
  elif have security && security find-generic-password -s "$KEY_SERVICE" >/dev/null 2>&1; then
    line ok "API key" "saved in your Keychain (cloud models enabled)"
  else
    line optional "API key" "not set; only needed for cloud models. Add it on the panel's Home page"
  fi
fi

# ---------- summary ----------
if [ "$PROBLEMS" -gt 0 ]; then
  echo
  echo "Not ready: $PROBLEMS problem(s) above. Fix them and run panel/setup.sh again."
  exit 1
fi
if [ "$QUIET" -ne 1 ]; then
  echo
  echo "Ready. Start the panel with: panel/run.sh"
fi
exit 0
