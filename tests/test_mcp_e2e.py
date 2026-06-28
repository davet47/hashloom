"""End-to-end: spawn `heddle serve` over stdio and exercise every tool the way
an agent would."""

import json
import sys

import anyio
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def call(project_root, requests):
    """Spin up the server once, run a sequence of (tool, args) calls."""

    async def _run():
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "heddle.cli", "serve"],
            cwd=str(project_root),
        )
        out = []
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = {t.name for t in (await session.list_tools()).tools}
                out.append(tools)
                for tool, args in requests:
                    result = await session.call_tool(tool, args)
                    out.append(json.loads(result.content[0].text))
        return out

    return anyio.run(_run)


@pytest.mark.e2e
def test_all_five_tools_over_stdio(project):
    root, store = project
    store.close()

    new_yaml = (root / "contracts" / "total.yaml").read_text().replace(
        "(items: list[Item]) -> float", "(items: list[Item]) -> int"
    )
    tools, packet, deps, verified, put, status = call(
        root,
        [
            ("get_contract", {"name": "report"}),
            ("get_dependents", {"name": "Item", "transitive": True}),
            ("verify", {"names": ["total", "report"]}),
            ("put_contract", {"name": "total", "yaml_text": new_yaml}),
            ("status", {}),
        ],
    )

    assert tools == {"get_contract", "put_contract", "get_dependents", "verify", "status"}

    assert packet["name"] == "report"
    assert {d["name"] for d in packet["deps"]} == {"Item", "total"}

    assert [d["name"] for d in deps["dependents"]] == ["report", "total"]

    assert {r["name"]: r["status"] for r in verified["results"]} == {"total": "pass", "report": "pass"}

    assert put["changed"] is True and put["invalidated"] == ["report"]

    # the contract edit dirtied both units again, and every byte served was counted
    assert set(status["dirty"]) == {"total", "report"}
    assert status["tokens"]["total"] > 0
    # 'status' counts itself only after responding, so it's absent from its own first report
    assert set(status["tokens"]["by_tool"]) == {"get_contract", "get_dependents", "verify", "put_contract"}


@pytest.mark.e2e
def test_errors_are_structured_over_stdio(project):
    root, store = project
    store.close()
    _, missing, bad_dep = call(
        root,
        [
            ("get_contract", {"name": "reprot"}),
            ("put_contract", {"name": "x", "yaml_text": 'name: x\nsignature: "() -> None"\ndeps: [Itme]\n'}),
        ],
    )
    assert missing["error"]["code"] == "unknown_contract"
    assert "nearest: 'report'" in missing["error"]["message"]
    assert bad_dep["error"]["code"] == "unknown_dep"
    assert "nearest: 'Item'" in bad_dep["error"]["message"]
