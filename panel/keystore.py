"""Anthropic API key in the macOS Keychain, through the `security` command.

The key is only ever passed on stdin (`security -i`), never in the command line,
so it does not show up in the process list.
"""
import getpass
import re
import subprocess

SERVICE = "LearningPanel Anthropic API key"
KEY_PATTERNS = {
    "anthropic": re.compile(r"^sk-ant-[A-Za-z0-9_-]{20,200}$"),
    "openrouter": re.compile(r"^sk-or-[A-Za-z0-9_-]{20,200}$"),
}
ACCOUNT_RE = re.compile(r"^[A-Za-z0-9._-]+$")
NOT_FOUND = 44


class KeystoreError(Exception):
    pass


def provider_of(key):
    """'anthropic' or 'openrouter' from the key's prefix, or None when it is neither (or malformed)."""
    if not isinstance(key, str):
        return None
    return next((name for name, pattern in KEY_PATTERNS.items() if pattern.match(key)), None)


def valid_key_format(key):
    return provider_of(key) is not None


def key_format_error(key):
    """Plain-language reason a key is not accepted, or None when it is fine."""
    if provider_of(key):
        return None
    if isinstance(key, str) and key.startswith("sk-") and not key.startswith(("sk-ant-", "sk-or-")):
        return ("That looks like an OpenAI key. OpenAI keys can't run the Claude models in this list. "
                "Use an OpenRouter key (sk-or-...), which reaches Claude, or an Anthropic key (sk-ant-...).")
    return "That does not look like an Anthropic or OpenRouter API key (it starts with sk-ant- or sk-or-)."


def _run(args, input=None):
    return subprocess.run(args, input=input, capture_output=True, text=True, timeout=15)


class Keystore:
    def __init__(self, run=None, account=None):
        self._run = run or _run
        self.account = account or getpass.getuser()
        if not ACCOUNT_RE.match(self.account):
            raise KeystoreError("Could not use this account name with the Keychain.")

    def _call(self, args, input=None):
        try:
            return self._run(args, input=input)
        except (OSError, subprocess.SubprocessError) as exc:
            raise KeystoreError("Could not reach the Keychain.") from exc

    def get_key(self):
        proc = self._call(["security", "find-generic-password", "-a", self.account, "-s", SERVICE, "-w"])
        if proc.returncode == NOT_FOUND:
            return None
        if proc.returncode != 0:
            raise KeystoreError("Could not read the Keychain.")
        return proc.stdout.strip() or None

    def set_key(self, key):
        error = key_format_error(key)
        if error:
            raise ValueError(error)
        command = f'add-generic-password -a "{self.account}" -s "{SERVICE}" -w "{key}" -U\n'
        proc = self._call(["security", "-i"], input=command)
        if proc.returncode != 0 or self.get_key() != key:
            raise KeystoreError("Could not save the key to the Keychain.")

    def delete_key(self):
        proc = self._call(["security", "delete-generic-password", "-a", self.account, "-s", SERVICE])
        if proc.returncode not in (0, NOT_FOUND):
            raise KeystoreError("Could not remove the key from the Keychain.")

    def status(self):
        key = self.get_key()
        return {"saved": bool(key), "last4": key[-4:] if key else None, "provider": provider_of(key) if key else None}
