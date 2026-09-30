"""panel/setup.sh: checks every requirement, installs what is missing, reports.

The script runs against stand-in commands (python3, ollama, brew, curl, security) placed first on PATH,
so nothing on the real machine is touched. It runs under /bin/bash (3.2 on macOS) on purpose.
"""
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SETUP = ROOT / "panel" / "setup.sh"
RUN = ROOT / "panel" / "run.sh"

HEADER = '#!/bin/bash\necho "$(basename "$0") $*" >> "$STUB_LOG"\n'

PYTHON3 = HEADER + r'''
case "$1" in
  --version) echo "Python 3.12.1"; exit 0;;
  -m) if [ "$2" = "venv" ]; then mkdir -p "$3/bin"; cp "$STUB_VENV_PY" "$3/bin/python"; chmod +x "$3/bin/python"; exit 0; fi;;
  -c) case "$2" in *version_info*) [ -f "$STUB_STATE/py_ok" ] && exit 0 || exit 1;; esac;;
esac
exit 0
'''
VENV_PY = HEADER + r'''
case "$1" in
  -c) case "$2" in *youtube_transcript_api*) [ -f "$STUB_STATE/lib_ok" ] && exit 0 || exit 1;; esac;;
  -m) if [ "$2" = "pip" ]; then [ -f "$STUB_STATE/pip_fail" ] && exit 1; touch "$STUB_STATE/lib_ok"; exit 0; fi;;
esac
exit 0
'''
OLLAMA = HEADER + r'''
case "$1" in
  --version) echo "ollama version is 9.9.9"; exit 0;;
  serve) touch "$STUB_STATE/up"; exit 0;;
  pull) [ -f "$STUB_STATE/pull_fail" ] && exit 1; echo "$2" >> "$STUB_STATE/models.txt"; exit 0;;
esac
exit 0
'''
CURL = HEADER + r'''
url=""; for a in "$@"; do case "$a" in http*) url="$a";; esac; done
case "$url" in
  *11434/api/tags*)
    [ -f "$STUB_STATE/up" ] || exit 7
    printf '{"models":['; sep=""
    if [ -f "$STUB_STATE/models.txt" ]; then
      while read -r m; do printf '%s{"name":"%s","model":"%s"}' "$sep" "$m" "$m"; sep=","; done < "$STUB_STATE/models.txt"
    fi
    printf ']}'; exit 0;;
  *youtube.com*) [ -f "$STUB_STATE/net_down" ] && exit 6; exit 0;;
esac
exit 0
'''
BREW = HEADER + r'''
case "$*" in
  "install ollama") cp "$STUB_OLLAMA_SRC" "$STUB_BIN/ollama"; chmod +x "$STUB_BIN/ollama"; exit 0;;
  "install python@3.12") touch "$STUB_STATE/py_ok"; exit 0;;
esac
exit 0
'''
SECURITY = HEADER + r'''
[ -f "$STUB_STATE/key" ] && exit 0 || exit 44
'''


def _write(path, text):
    path.write_text(text)
    path.chmod(0o755)


class Machine:
    """A fake machine. Defaults describe a fully set-up Mac."""

    def __init__(self, tmp, *, python=True, ollama=True, brew=False, running=True, models=("qwen3.5:9b",),
                 venv=True, lib=True, net=True, key=False):
        self.tmp, self.bin, self.state = tmp, tmp / "bin", tmp / "state"
        self.venv, self.log = tmp / "venv", tmp / "calls.log"
        for d in (self.bin, self.state, tmp / "tmp"):
            d.mkdir(exist_ok=True)
        self.log.write_text("")
        (tmp / "requirements.txt").write_text("youtube-transcript-api>=1.0\n")
        _write(tmp / "venv_py_stub", VENV_PY)
        _write(tmp / "ollama_stub", OLLAMA)
        _write(self.bin / "python3", PYTHON3)
        _write(self.bin / "curl", CURL)
        _write(self.bin / "security", SECURITY)
        if python:
            (self.state / "py_ok").write_text("")
        if ollama:
            _write(self.bin / "ollama", OLLAMA)
        if brew:
            _write(self.bin / "brew", BREW)
        if running:
            (self.state / "up").write_text("")
        if models:
            (self.state / "models.txt").write_text("\n".join(models) + "\n")
        if venv:
            (self.venv / "bin").mkdir(parents=True)
            _write(self.venv / "bin" / "python", VENV_PY)
        if lib:
            (self.state / "lib_ok").write_text("")
        if not net:
            (self.state / "net_down").write_text("")
        if key:
            (self.state / "key").write_text("")

    def flag(self, name):
        (self.state / name).write_text("")

    def run(self, *args):
        env = {
            "PATH": f"{self.bin}:/usr/bin:/bin", "HOME": str(self.tmp), "TMPDIR": str(self.tmp / "tmp"),
            "STUB_LOG": str(self.log), "STUB_STATE": str(self.state), "STUB_BIN": str(self.bin),
            "STUB_VENV_PY": str(self.tmp / "venv_py_stub"), "STUB_OLLAMA_SRC": str(self.tmp / "ollama_stub"),
            "PANEL_VENV_DIR": str(self.venv), "PANEL_REQUIREMENTS": str(self.tmp / "requirements.txt"),
        }
        proc = subprocess.run(["/bin/bash", str(SETUP), *args], env=env, capture_output=True, text=True, timeout=60)
        return proc.returncode, proc.stdout + proc.stderr

    def calls(self):
        return self.log.read_text().splitlines()

    def installs(self):
        return [c for c in self.calls() if c.startswith(("brew install", "ollama pull", "ollama serve", "python -m pip"))
                or c.startswith("python3 -m venv")]


def test_a_fully_set_up_machine_reports_ready_and_installs_nothing(tmp_path):
    m = Machine(tmp_path, key=True)
    rc, out = m.run()
    assert rc == 0 and "Ready" in out
    assert m.installs() == []
    for label in ("Python", "Python library", "Ollama", "Ollama running", "Local model", "YouTube", "API key"):
        assert label in out
    assert "MISSING" not in out and "FAILED" not in out


def test_check_mode_reports_but_never_installs(tmp_path):
    m = Machine(tmp_path, ollama=False, brew=True, running=False, models=(), venv=False, lib=False, python=False)
    rc, out = m.run("--check")
    assert rc == 1 and "MISSING" in out
    assert m.installs() == []
    assert "brew install ollama" in out            # tells you how to fix it


def test_missing_ollama_is_installed_with_brew_started_and_given_the_default_model(tmp_path):
    m = Machine(tmp_path, ollama=False, brew=True, running=False, models=())
    rc, out = m.run()
    assert rc == 0, out
    installs = m.installs()
    assert installs == ["brew install ollama", "ollama serve", "ollama pull qwen3.5:9b"]
    assert out.count("installed") >= 2 and "started" in out and "Ready" in out


def test_missing_ollama_without_brew_is_reported_with_a_download_link(tmp_path):
    m = Machine(tmp_path, ollama=False, brew=False)
    rc, out = m.run()
    assert rc == 1 and "https://ollama.com/download" in out and "FAILED" in out
    assert not any(c.startswith("ollama") for c in m.calls())


def test_ollama_installed_but_not_running_gets_started(tmp_path):
    m = Machine(tmp_path, running=False)
    rc, out = m.run()
    assert rc == 0 and m.installs() == ["ollama serve"] and "started" in out


def test_any_qwen_model_counts_and_the_effort_levels_are_reported(tmp_path):
    m = Machine(tmp_path, models=("qwen3.5:2b",))
    rc, out = m.run()
    assert rc == 0 and not any(c.startswith("ollama pull") for c in m.calls())
    assert "available: Easy(2b)" in out and "not installed: Medium(9b), Hard(27b)" in out
    assert "available: available" not in out           # no repeated wording


def test_no_model_pulls_the_default_and_a_failed_pull_is_a_problem(tmp_path):
    m = Machine(tmp_path, models=())
    m.flag("pull_fail")
    rc, out = m.run()
    assert rc == 1 and "ollama pull qwen3.5:9b" in m.calls() and "FAILED" in out


def test_missing_environment_and_library_are_created_and_installed(tmp_path):
    m = Machine(tmp_path, venv=False, lib=False)
    rc, out = m.run()
    assert rc == 0, out
    assert m.installs()[0].startswith("python3 -m venv") and any("pip" in c and "install" in c for c in m.installs())
    assert "installed" in out and (m.venv / "bin" / "python").exists()


def test_a_failing_pip_install_is_reported_not_hidden(tmp_path):
    m = Machine(tmp_path, lib=False)
    m.flag("pip_fail")
    rc, out = m.run()
    assert rc == 1 and "FAILED" in out and "Python library" in out


def test_old_python_is_upgraded_with_brew_or_explained_without_it(tmp_path):
    with_brew = Machine(tmp_path / "a", python=False, brew=True) if (tmp_path / "a").mkdir() is None else None
    rc, out = with_brew.run()
    assert rc == 0 and "brew install python@3.12" in with_brew.calls()
    no_brew = Machine(tmp_path / "b", python=False) if (tmp_path / "b").mkdir() is None else None
    rc, out = no_brew.run()
    assert rc == 1 and "Python 3.9" in out and "brew.sh" in out


def test_no_internet_and_no_api_key_are_warnings_not_failures(tmp_path):
    m = Machine(tmp_path, net=False, key=False)
    rc, out = m.run()
    assert rc == 0 and "warning" in out and "optional" in out
    assert "Home page" in out                         # says where to add the key


def test_quiet_mode_prints_nothing_when_all_is_well_and_only_changes_otherwise(tmp_path):
    ok = Machine(tmp_path / "ok", key=True) if (tmp_path / "ok").mkdir() is None else None
    rc, out = ok.run("--quiet")
    assert rc == 0 and out.strip() == ""
    fix = Machine(tmp_path / "fix", running=False) if (tmp_path / "fix").mkdir() is None else None
    rc, out = fix.run("--quiet")
    assert rc == 0 and "started" in out and "Python library" not in out       # only what needed attention
    assert not any(c.startswith("curl") and "youtube" in c for c in fix.calls())  # quiet mode skips the slow checks


def test_unknown_option_is_rejected(tmp_path):
    rc, out = Machine(tmp_path).run("--bogus")
    assert rc == 2 and "Unknown option" in out


def test_run_sh_sets_up_first_and_can_skip_it():
    text = RUN.read_text()
    assert "setup.sh" in text and "--quiet" in text and "PANEL_SKIP_SETUP" in text
    assert text.index("setup.sh") < text.index("server.py")
    for script in (SETUP, RUN):
        assert os.access(script, os.X_OK)
        assert subprocess.run(["/bin/bash", "-n", str(script)]).returncode == 0
