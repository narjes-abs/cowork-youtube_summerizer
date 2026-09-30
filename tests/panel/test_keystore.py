import shlex
from types import SimpleNamespace

import pytest

import keystore as ks

KEY = "sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789"


class FakeSecurity:
    """In-memory stand-in for the `security` command."""

    def __init__(self, fail_write=False):
        self.items, self.calls, self.fail_write = {}, [], fail_write

    def __call__(self, args, input=None):
        self.calls.append((list(args), input))
        if args[:2] == ["security", "find-generic-password"]:
            k = self.items.get("key")
            return SimpleNamespace(returncode=0 if k else 44, stdout=(k + "\n") if k else "", stderr="")
        if args == ["security", "-i"]:
            words = shlex.split(input)
            assert words[0] == "add-generic-password"
            if self.fail_write:
                return SimpleNamespace(returncode=1, stdout="", stderr="denied")
            self.items["key"] = words[words.index("-w") + 1]
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if args[:2] == ["security", "delete-generic-password"]:
            existed = self.items.pop("key", None)
            return SimpleNamespace(returncode=0 if existed else 44, stdout="", stderr="")
        raise AssertionError(args)


def test_round_trip_and_status():
    sec = FakeSecurity()
    store = ks.Keystore(run=sec, account="tester")
    assert store.get_key() is None and store.status() == {"saved": False, "last4": None, "provider": None}
    store.set_key(KEY)
    assert store.get_key() == KEY
    assert store.status() == {"saved": True, "last4": KEY[-4:], "provider": "anthropic"}
    store.delete_key()
    assert store.get_key() is None
    store.delete_key()  # deleting nothing is fine


def test_key_is_never_in_argv_only_on_stdin():
    sec = FakeSecurity()
    ks.Keystore(run=sec, account="tester").set_key(KEY)
    for args, stdin in sec.calls:
        assert KEY not in " ".join(args)
    assert any(stdin and KEY in stdin for _, stdin in sec.calls)


@pytest.mark.parametrize("bad", [
    "", "   ", "sk-ant-short", 'sk-ant-abcdefghijklmnopqrstuvwxyz" ; delete-generic-password -a x',
    "sk-ant-abcdefghijklmnopqrstuvwxyz\nadd-generic-password", "sk-ant-abcdefghij klmnopqrstuvwxyz",
    "sk-ant-abcdefghijklmnopqrstuvwxyz`id`", "sk-ant-abcdefghijklmnopqrstuvwxyz$(id)", "not-a-key" * 5,
])
def test_bad_keys_never_reach_the_security_command(bad):
    sec = FakeSecurity()
    with pytest.raises(ValueError):
        ks.Keystore(run=sec, account="tester").set_key(bad)
    assert sec.calls == []
    assert ks.valid_key_format(bad) is False


def test_keychain_failure_message_has_no_key():
    store = ks.Keystore(run=FakeSecurity(fail_write=True), account="tester")
    with pytest.raises(ks.KeystoreError) as exc:
        store.set_key(KEY)
    assert KEY not in str(exc.value) and "Keychain" in str(exc.value)


def test_write_that_silently_did_not_stick_is_an_error():
    class Liar(FakeSecurity):
        def __call__(self, args, input=None):
            if args == ["security", "-i"]:
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            return super().__call__(args, input)

    with pytest.raises(ks.KeystoreError):
        ks.Keystore(run=Liar(), account="tester").set_key(KEY)


def test_unusual_account_names_are_rejected():
    with pytest.raises(ks.KeystoreError):
        ks.Keystore(run=FakeSecurity(), account='mo"lly')


def test_replacing_an_existing_key_updates_it():
    sec = FakeSecurity()
    store = ks.Keystore(run=sec, account="tester")
    store.set_key(KEY)
    newer = "sk-ant-api03-ZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZ9999"
    store.set_key(newer)
    assert store.get_key() == newer and store.status()["last4"] == "9999"


OR_KEY = "sk-or-v1-abcdefghijklmnopqrstuvwxyz0123456789abcdef"
OPENAI_KEY = "sk-proj-abcdefghijklmnopqrstuvwxyz0123456789"


def test_provider_is_detected_from_the_prefix():
    assert ks.provider_of(KEY) == "anthropic"
    assert ks.provider_of(OR_KEY) == "openrouter"
    assert ks.provider_of(OPENAI_KEY) is None and ks.provider_of("") is None and ks.provider_of(None) is None
    assert ks.valid_key_format(OR_KEY) and not ks.valid_key_format(OPENAI_KEY)


def test_openrouter_key_round_trip_and_status():
    sec = FakeSecurity()
    store = ks.Keystore(run=sec, account="tester")
    store.set_key(OR_KEY)
    assert store.status() == {"saved": True, "last4": OR_KEY[-4:], "provider": "openrouter"}
    assert all(OR_KEY not in " ".join(args) for args, _ in sec.calls)


def test_switching_provider_replaces_the_single_saved_key():
    store = ks.Keystore(run=FakeSecurity(), account="tester")
    store.set_key(KEY)
    store.set_key(OR_KEY)
    assert store.get_key() == OR_KEY and store.status()["provider"] == "openrouter"


def test_openai_keys_get_a_specific_explanation():
    assert "OpenRouter" in ks.key_format_error(OPENAI_KEY) and "Claude" in ks.key_format_error(OPENAI_KEY)
    assert "sk-or-" in ks.key_format_error("nope") and "sk-ant-" in ks.key_format_error("nope")
    assert ks.key_format_error(OR_KEY) is None
    with pytest.raises(ValueError, match="OpenRouter"):
        ks.Keystore(run=FakeSecurity(), account="tester").set_key(OPENAI_KEY)


@pytest.mark.parametrize("bad", [
    'sk-or-abcdefghijklmnopqrstuvwxyz" ; delete-generic-password -a x',
    "sk-or-abcdefghijklmnopqrstuvwxyz\nadd-generic-password", "sk-or-abcdefghij klmnopqrstuvwxyz", "sk-or-abcdefghijklmnopqrstuvwxyz$(id)",
])
def test_openrouter_style_injection_attempts_never_reach_security(bad):
    sec = FakeSecurity()
    with pytest.raises(ValueError):
        ks.Keystore(run=sec, account="tester").set_key(bad)
    assert sec.calls == []
