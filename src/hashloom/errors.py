"""Structured errors. Every tool returns {error: {code, message, contract?}}, never a stack trace."""

from __future__ import annotations

import difflib


class HashloomError(Exception):
    def __init__(self, code: str, message: str, contract: str | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.contract = contract

    def to_dict(self) -> dict:
        err: dict = {"code": self.code, "message": self.message}
        if self.contract is not None:
            err["contract"] = self.contract
        return {"error": err}


def unknown_name(code: str, missing: str, known: list[str], contract: str | None = None) -> HashloomError:
    """Build an unknown-name error with a nearest-match suggestion."""
    near = difflib.get_close_matches(missing, known, n=1)
    hint = f" — nearest: '{near[0]}'" if near else ""
    return HashloomError(code, f"'{missing}' not found{hint}", contract=contract)
