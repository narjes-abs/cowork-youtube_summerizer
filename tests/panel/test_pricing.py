import pricing

RAW = {"data": [
    {"id": "anthropic/claude-haiku-4.5", "pricing": {"prompt": "0.000001", "completion": "0.000005"}},
    {"id": "anthropic/claude-sonnet-5.5", "pricing": {"prompt": "0.000002", "completion": "0.00001"}},
    {"id": "broken/model", "pricing": {"prompt": "free"}},
    {"id": "no-pricing"},
]}


def test_per_million_and_cost():
    book = pricing.PriceBook(fetch=lambda: RAW)
    assert book.per_million("anthropic/claude-haiku-4.5") == {"in": 1.0, "out": 5.0}
    assert book.per_million("broken/model") is None and book.per_million("nope") is None
    assert abs(book.cost("anthropic/claude-sonnet-5.5", 12340, 1020) - (12340 * 2e-6 + 1020 * 1e-5)) < 1e-9
    assert book.cost("nope", 1, 1) is None


def test_a_failed_fetch_means_no_prices_not_a_crash():
    def boom():
        raise OSError("offline")

    book = pricing.PriceBook(fetch=boom)
    assert book.per_million("anthropic/claude-haiku-4.5") is None
    assert book.cost("anthropic/claude-haiku-4.5", 10, 10) is None


def test_prices_are_cached_and_stale_data_survives_a_later_failure():
    calls = {"n": 0, "fail": False}

    def fetch():
        calls["n"] += 1
        if calls["fail"]:
            raise OSError("offline")
        return RAW

    book = pricing.PriceBook(fetch=fetch, ttl=0.05)
    book.per_million("anthropic/claude-haiku-4.5")
    book.per_million("anthropic/claude-haiku-4.5")
    assert calls["n"] == 1                       # cached inside the ttl
    import time
    time.sleep(0.08)
    calls["fail"] = True
    assert book.per_million("anthropic/claude-haiku-4.5") == {"in": 1.0, "out": 5.0}  # stale beats nothing
