"""The `_respond` wrapper: structured errors, never a stack trace, token counters."""

import json

import anyio

from hashloom.server import build_server


def rpc(mcp, tool, args):
    async def _run():
        return await mcp.call_tool(tool, args)

    result = anyio.run(_run)
    if isinstance(result, tuple):  # (content, structured) on newer SDKs
        result = result[0]
    return json.loads(result[0].text)


def test_happy_path_counts_tokens(project):
    root, store = project
    store.close()  # build_server opens its own connection to the same db
    mcp = build_server(root)
    first = rpc(mcp, "status", {})
    assert first["contracts"] == 3
    # the first call's response was token-counted into the store
    second = rpc(mcp, "status", {})
    assert second["tokens"]["by_tool"]["status"] > 0


def test_hashloom_error_comes_back_structured(project):
    root, store = project
    store.close()
    mcp = build_server(root)
    result = rpc(mcp, "get_contract", {"name": "Itme"})
    assert result["error"]["code"] == "unknown_contract"
    assert "nearest: 'Item'" in result["error"]["message"]


def test_unexpected_exception_never_leaks_a_stack_trace(project, monkeypatch):
    root, store = project
    store.close()
    mcp = build_server(root)

    def boom(*args, **kwargs):
        raise ValueError("boom")

    monkeypatch.setattr("hashloom.api.status", boom)
    result = rpc(mcp, "status", {})
    assert result["error"]["code"] == "internal"
    assert result["error"]["message"] == "ValueError: boom"
    assert "Traceback" not in json.dumps(result)
