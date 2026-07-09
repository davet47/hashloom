"""Token counting (tiktoken cl100k as proxy), with an offline fallback."""

from __future__ import annotations

_ENCODER = None
_FALLBACK = False


def _encoder():
    global _ENCODER, _FALLBACK
    if _ENCODER is None and not _FALLBACK:
        try:
            import tiktoken

            _ENCODER = tiktoken.get_encoding("cl100k_base")
        except Exception:
            _FALLBACK = True  # offline or tiktoken unavailable — use chars/4
    return _ENCODER


def count(text: str) -> int:
    enc = _encoder()
    if enc is None:
        return max(1, len(text) // 4)
    return len(enc.encode(text))


def truncate(text: str, max_tokens: int) -> str:
    enc = _encoder()
    if enc is None:
        limit = max_tokens * 4
        return text if len(text) <= limit else text[: limit - 1] + "…"
    toks = enc.encode(text)
    if len(toks) <= max_tokens:
        return text
    return enc.decode(toks[: max_tokens - 1]) + "…"
