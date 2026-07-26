"""The offline chars/4 fallback when tiktoken is unavailable."""

import sys

from hashloom import tokens


def test_count_and_truncate_fall_back_to_chars(monkeypatch):
    monkeypatch.setattr(tokens, "_ENCODER", None)
    monkeypatch.setattr(tokens, "_FALLBACK", True)
    assert tokens.count("x" * 40) == 10
    assert tokens.count("") == 1  # never zero
    long_text = "y" * 100
    assert tokens.truncate(long_text, 10) == "y" * 39 + "…"
    assert tokens.truncate("short", 10) == "short"


def test_encoder_import_failure_sets_the_fallback(monkeypatch):
    monkeypatch.setattr(tokens, "_ENCODER", None)
    monkeypatch.setattr(tokens, "_FALLBACK", False)
    monkeypatch.setitem(sys.modules, "tiktoken", None)  # makes the import raise
    assert tokens._encoder() is None
    assert tokens._FALLBACK is True
