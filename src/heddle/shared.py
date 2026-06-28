"""A shared verification cache, behind the Store interface.

`LayeredStore` fronts a local Store with a shared one for the two team-portable
kinds of state: verification verdicts and impl-source blobs. Everything else
stays local. A local miss reads through to the shared store and back-fills
locally; a green result (and its blobs) writes through to the shared store. The
shared store is just another Store, so today it is a second sqlite file and
later, behind the same Protocol, a hosted/remote backend, with no change to
callers.

This is the thin MVP of the v0.2 "solo -> team" theme. The hard parts of a real
hosted service (auth, concurrent writers, cross-graph invalidation, a trust
model for who may publish a green) are deferred; see docs/hosted-store.md.
"""

from __future__ import annotations

from .store import Store


class LayeredStore:
    """A Store that shares verdicts and blobs through a second Store.

    `local` holds this developer's full state; `shared` is the team-portable
    cache (verifications + blobs). All other operations delegate to `local`.
    """

    def __init__(self, local: Store, shared: Store):
        self._local = local
        self._shared = shared

    # -- verification verdicts: read-through, write-through (greens only) ----

    def get_verification(self, key: str) -> dict | None:
        v = self._local.get_verification(key)
        if v is not None:
            return v
        shared = self._shared.get_verification(key)
        if shared is not None and shared["status"] == "pass" and not shared["stale"]:
            # back-fill so the next read is local; never import a fail or a stale row
            self._local.record_verification(key, shared["contract_name"], "pass", shared["summary"])
            return self._local.get_verification(key)
        return None

    def record_verification(self, key: str, contract_name: str, status: str, summary: str) -> None:
        self._local.record_verification(key, contract_name, status, summary)
        if status == "pass":
            self._shared.record_verification(key, contract_name, status, summary)  # publish only greens

    # -- impl-source blobs: read-through, write-through ---------------------

    def get_blob(self, blob_hash: str) -> str | None:
        return self._local.get_blob(blob_hash) or self._shared.get_blob(blob_hash)

    def put_blob(self, content: str) -> str:
        h = self._local.put_blob(content)
        self._shared.put_blob(content)
        return h

    # -- everything else is local -------------------------------------------

    def __getattr__(self, name: str):
        # contracts, edges, impls, counters, close, ... are per-developer state;
        # only verdicts and blobs cross the team boundary
        return getattr(self._local, name)
