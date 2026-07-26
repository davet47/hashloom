"""The shared verification cache over HTTP: a green verified by one client is
served to another through the cache_server; failures are never published; a
shared-store outage degrades cleanly to local verify; and the bearer token is
enforced. Mirrors tests/test_shared_store.py, but over the real transport."""

from __future__ import annotations

import json
import textwrap
import threading
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from hashloom import api
from hashloom.cache_server import CacheServer, CacheStore
from hashloom.config import resolve_shared_store
from hashloom.errors import HashloomError
from hashloom.indexer import index
from hashloom.project import init_project
from hashloom.remote import RemoteStore
from hashloom.shared import LayeredStore
from hashloom.store import SqliteStore
from hashloom.verify import verify_one

_TOKEN = "test-token"


def _make_project(root: Path) -> None:
    init_project(root)
    (root / "src").mkdir()
    (root / "tests").mkdir()
    (root / "src" / "__init__.py").write_text("")
    (root / "tests" / "__init__.py").write_text("")
    (root / "contracts" / "total.yaml").write_text(textwrap.dedent("""
        name: total
        signature: "(xs: list[int]) -> int"
        tests: [tests/test_x.py::test_total]
        impl: src/x.py::total
    """).strip() + "\n")
    (root / "src" / "x.py").write_text("def total(xs):\n    return sum(xs)\n")
    (root / "tests" / "test_x.py").write_text(
        "from src.x import total\n\n\ndef test_total():\n    assert total([1, 2]) == 3\n"
    )


@pytest.fixture
def cache(tmp_path):
    """A running cache_server on an ephemeral port; yields (base_url, token)."""
    store = CacheStore(tmp_path / "cache.db", check_same_thread=False)
    httpd = CacheServer(("127.0.0.1", 0), store, _TOKEN)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}", _TOKEN
    finally:
        httpd.shutdown()
        thread.join(timeout=5)
        httpd.server_close()
        store.close()


def _raw(method: str, base: str, token: str, path: str, body: dict | None = None) -> int:
    """Make a raw request, returning just the HTTP status (for auth/guard checks)."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code


def test_shared_green_served_to_second_client_over_http(cache, tmp_path):
    base, token = cache
    root = tmp_path / "proj"
    root.mkdir()
    _make_project(root)

    # client A: local + remote shared. verify runs pytest once and publishes.
    a_local = SqliteStore(root / ".hashloom" / "a.db")
    a = LayeredStore(a_local, RemoteStore(base, token))
    index(root, a)
    assert api.verify(root, a, ["total"])["results"][0]["status"] == "pass"
    assert a_local.counters().get("test_runs", 0) == 1

    # blobs wrote through over HTTP (serve weft, not only verdicts)
    blob_hash = a_local.get_impl("total")["blob_hash"]
    assert RemoteStore(base, token).get_blob(blob_hash) is not None

    # client B: fresh local, same remote. the green is served WITHOUT pytest.
    b_local = SqliteStore(root / ".hashloom" / "b.db")
    b = LayeredStore(b_local, RemoteStore(base, token))
    index(root, b)
    assert api.verify(root, b, ["total"])["results"][0]["status"] == "cached-pass"
    assert b_local.counters().get("test_runs", 0) == 0
    a_local.close()
    b_local.close()


def test_failures_not_published_over_http(cache, tmp_path):
    base, token = cache
    root = tmp_path / "proj"
    root.mkdir()
    _make_project(root)
    (root / "src" / "x.py").write_text("def total(xs):\n    return 0\n")  # wrong

    a = LayeredStore(SqliteStore(root / ".hashloom" / "a.db"), RemoteStore(base, token))
    index(root, a)
    r = verify_one(root, a, "total")  # verify_one exposes the cache key (api.verify hides it)
    assert r["status"] == "fail"
    # the failed key was never published to the shared store
    assert RemoteStore(base, token).get_verification(r["key"]) is None
    # and the server itself rejects a hand-posted non-green verdict
    assert _raw("POST", base, token, "/verification",
                {"key": r["key"], "contract_name": "total", "status": "fail", "summary": "x"}) == 400

    # a second client re-runs and also fails; no shared green crossed the boundary
    b = LayeredStore(SqliteStore(root / ".hashloom" / "b.db"), RemoteStore(base, token))
    index(root, b)
    assert api.verify(root, b, ["total"])["results"][0]["status"] == "fail"


def test_unreachable_shared_degrades_to_local_verify(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    _make_project(root)
    dead = RemoteStore("http://127.0.0.1:1", _TOKEN, timeout=1.0)  # nothing listens
    local = SqliteStore(root / ".hashloom" / "x.db")
    store = LayeredStore(local, dead)

    index(root, store)  # blob write-through to a dead store must not raise
    r = api.verify(root, store, ["total"])["results"][0]
    assert r["status"] == "pass"  # ran pytest locally, no exception
    assert local.counters().get("test_runs", 0) == 1
    # second verify is served from the LOCAL row (shared still dead) — no re-run
    assert api.verify(root, store, ["total"])["results"][0]["status"] == "cached-pass"
    assert local.counters().get("test_runs", 0) == 1
    local.close()


def test_auth_rejected_but_verify_still_degrades(cache, tmp_path):
    base, _ = cache
    # the server enforces the token...
    assert _raw("GET", base, "wrong-token", "/verification/whatever") == 401
    # ...and a client with the wrong token degrades (verify still runs locally)
    root = tmp_path / "proj"
    root.mkdir()
    _make_project(root)
    local = SqliteStore(root / ".hashloom" / "x.db")
    store = LayeredStore(local, RemoteStore(base, "wrong-token"))
    index(root, store)
    assert api.verify(root, store, ["total"])["results"][0]["status"] == "pass"
    assert local.counters().get("test_runs", 0) == 1
    local.close()


# -- auth scoping: split publish from read ----------------------------------

_PUBLISH_TOKEN = "publish-token"


@pytest.fixture
def scoped_cache(tmp_path):
    """A cache_server with split read/publish tokens; yields (base_url, server_store)."""
    store = CacheStore(tmp_path / "cache.db", check_same_thread=False)
    httpd = CacheServer(("127.0.0.1", 0), store, _TOKEN, publish_token=_PUBLISH_TOKEN)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}", store
    finally:
        httpd.shutdown()
        thread.join(timeout=5)
        httpd.server_close()
        store.close()


def test_read_token_reads_but_cannot_publish(scoped_cache):
    base, _ = scoped_cache
    assert _raw("GET", base, _TOKEN, "/verification/whatever") == 404  # authed, no such row
    assert _raw("POST", base, _TOKEN, "/blob", {"content": "x"}) == 403
    assert _raw("POST", base, _TOKEN, "/verification",
                {"key": "k", "contract_name": "c", "status": "pass", "summary": ""}) == 403


def test_publish_token_implies_read(scoped_cache):
    base, store = scoped_cache
    assert _raw("GET", base, _PUBLISH_TOKEN, "/verification/whatever") == 404  # reads too
    assert _raw("POST", base, _PUBLISH_TOKEN, "/blob", {"content": "x"}) == 200
    assert _raw("POST", base, _PUBLISH_TOKEN, "/verification",
                {"key": "k", "contract_name": "c", "status": "pass", "summary": ""}) == 204
    assert store.get_verification("k")["status"] == "pass"


def test_unknown_token_is_401_on_both_verbs(scoped_cache):
    base, _ = scoped_cache
    assert _raw("GET", base, "wrong-token", "/verification/whatever") == 401
    assert _raw("POST", base, "wrong-token", "/blob", {"content": "x"}) == 401


def test_single_token_server_still_grants_both_roles(cache):
    # back-compat pin: with no publish token configured, --token publishes too
    base, token = cache
    assert _raw("POST", base, token, "/blob", {"content": "x"}) == 200


def test_ci_publishes_laptop_consumes(scoped_cache, tmp_path):
    base, server_store = scoped_cache
    root = tmp_path / "proj"
    root.mkdir()
    _make_project(root)

    # CI: publish token. verify runs pytest once and publishes the green.
    ci_local = SqliteStore(root / ".hashloom" / "ci.db")
    ci = LayeredStore(ci_local, RemoteStore(base, _PUBLISH_TOKEN))
    index(root, ci)
    assert api.verify(root, ci, ["total"])["results"][0]["status"] == "pass"

    # laptop: read token. the green is served over HTTP without pytest.
    lap_local = SqliteStore(root / ".hashloom" / "lap.db")
    lap = LayeredStore(lap_local, RemoteStore(base, _TOKEN))
    index(root, lap)
    assert api.verify(root, lap, ["total"])["results"][0]["status"] == "cached-pass"
    assert lap_local.counters().get("test_runs", 0) == 0

    # the laptop's own new green stays local: its publish is rejected (403),
    # swallowed, and verify still passes
    (root / "src" / "x.py").write_text("def total(xs):\n    return sum(xs) + 0\n")
    r = verify_one(root, lap, "total")
    assert r["status"] == "pass"
    assert server_store.get_verification(r["key"]) is None
    ci_local.close()
    lap_local.close()


def test_publish_false_client_skips_posts_entirely(cache, tmp_path):
    base, token = cache
    root = tmp_path / "proj"
    root.mkdir()
    _make_project(root)
    # even with a fully-capable token, publish=False never POSTs
    local = SqliteStore(root / ".hashloom" / "x.db")
    store = LayeredStore(local, RemoteStore(base, token, publish=False))
    index(root, store)
    r = verify_one(root, store, "total")
    assert r["status"] == "pass"
    assert RemoteStore(base, token).get_verification(r["key"]) is None  # nothing landed
    blob_hash = local.get_impl("total")["blob_hash"]
    assert RemoteStore(base, token).get_blob(blob_hash) is None  # blobs suppressed too
    local.close()


# -- concurrent writers: threaded server, first-writer-wins verdicts --------


def _raw_body(method: str, base: str, token: str, path: str, body: dict | None = None) -> tuple[int, str]:
    """Like _raw, but also returns the response body text."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8")


def _publish(base: str, token: str, key: str, summary: str = "") -> int:
    return _raw("POST", base, token, "/verification",
                {"key": key, "contract_name": "c", "status": "pass", "summary": summary})


def test_duplicate_publish_is_first_writer_wins(scoped_cache):
    base, store = scoped_cache
    assert _publish(base, _PUBLISH_TOKEN, "k1", summary="first") == 204
    first = store.get_verification("k1")
    assert _publish(base, _PUBLISH_TOKEN, "k1", summary="second") == 204
    after = store.get_verification("k1")
    assert after["summary"] == "first"        # the duplicate was a no-op
    assert after["ran_at"] == first["ran_at"]  # freshness stays honest


def test_duplicate_publish_does_not_unstale(scoped_cache):
    base, store = scoped_cache
    assert _publish(base, _PUBLISH_TOKEN, "k2") == 204
    assert store.mark_stale(["c"]) == 1
    # the race cross-graph invalidation would hit: a duplicate publish must
    # not resurrect a row that was just marked stale
    assert _publish(base, _PUBLISH_TOKEN, "k2") == 204
    assert store.get_verification("k2")["stale"] == 1


def test_concurrent_publish_and_read_storm(scoped_cache):
    base, store = scoped_cache
    shared_key = "shared-key"

    def worker(i: int) -> list[int]:
        return [
            _publish(base, _PUBLISH_TOKEN, f"key-{i}"),
            _publish(base, _PUBLISH_TOKEN, shared_key, summary=f"w{i}"),
            _raw("GET", base, _TOKEN, f"/verification/key-{i}"),
            _raw("POST", base, _PUBLISH_TOKEN, "/blob", {"content": f"content-{i % 3}"}),
        ]

    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(worker, range(16)))
    for codes in results:
        assert codes == [204, 204, 200, 200]  # no 5xx anywhere in the storm
    for i in range(16):
        assert store.get_verification(f"key-{i}") is not None
    # exactly one writer won the shared key, whole — never a blend
    assert store.get_verification(shared_key)["summary"] in {f"w{i}" for i in range(16)}


def test_unexpected_store_error_returns_structured_500(scoped_cache, monkeypatch):
    base, store = scoped_cache

    def boom(key):
        raise RuntimeError("boom")

    monkeypatch.setattr(store, "get_verification", boom)
    status, body = _raw_body("GET", base, _TOKEN, "/verification/x")
    assert status == 500
    assert json.loads(body)["error"]["code"] == "internal"
    assert "Traceback" not in body


def test_resolve_shared_store_validation(tmp_path):
    init_project(tmp_path)
    cfg = tmp_path / ".hashloom" / "config.json"

    cfg.write_text("{}")
    assert resolve_shared_store(tmp_path) is None  # no shared block -> local only

    cfg.write_text(json.dumps({"shared": {"url": "http://h", "token": "t"}}))
    assert resolve_shared_store(tmp_path) == {"url": "http://h", "token": "t", "publish": True}

    cfg.write_text(json.dumps({"shared": {"url": "http://h", "token": "t", "publish": False}}))
    assert resolve_shared_store(tmp_path)["publish"] is False

    for bad in ({"shared": "nope"},
                {"shared": {"token": "t"}},          # missing url
                {"shared": {"url": "http://h"}},      # missing token
                {"shared": {"url": "", "token": "t"}},   # empty url
                {"shared": {"url": "http://h", "token": "t", "publish": "no"}}):  # non-bool publish
        cfg.write_text(json.dumps(bad))
        with pytest.raises(HashloomError) as e:
            resolve_shared_store(tmp_path)
        assert e.value.code == "bad_config"
