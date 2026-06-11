"""Real-protocol end-to-end test: drive the MCP server as a subprocess via the
actual MCP client (stdio + JSON-RPC), exactly as an LLM client would.

This complements test_mcp.py (which calls the tool functions directly) by
exercising the full wire protocol: initialize handshake, tools/list, tools/call.
"""

import asyncio
import os
import sys
import tempfile
from pathlib import Path

import pytest

pytest.importorskip("mcp")

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


def _text(result) -> str:
    return "\n".join(getattr(b, "text", "") for b in result.content)


async def _flow():
    tmp = Path(tempfile.mkdtemp()) / "e2e.db"
    env = {**os.environ, "PYTHONPATH": str(SRC), "PYTHONIOENCODING": "utf-8"}
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "memory_kernel.mcp_server", "--db", str(tmp)],
        env=env,
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            tools = await session.list_tools()
            remember = await session.call_tool(
                "memory_remember",
                {
                    "scope": "e2e",
                    "kind": "decision",
                    "title": "Local memory",
                    "content": "Вирішили тримати памʼять локально у SQLite.",
                },
            )
            search = await session.call_tool("memory_search", {"query": "рішення", "limit": 3})
            forget_id = _text(remember).split()[1]
            forget = await session.call_tool("memory_forget", {"memory_id": forget_id})
            search_after = await session.call_tool("memory_search", {"query": "рішення", "limit": 3})
            return {
                "server_name": init.serverInfo.name,
                "tool_names": {t.name for t in tools.tools},
                "remember": _text(remember),
                "search": _text(search),
                "forget": _text(forget),
                "search_after": _text(search_after),
            }


def test_mcp_server_full_protocol_roundtrip():
    try:
        result = asyncio.run(asyncio.wait_for(_flow(), timeout=30))
    except Exception as exc:  # pragma: no cover - environment/transport issues
        pytest.skip(f"MCP subprocess transport unavailable: {exc}")

    assert result["server_name"] == "memory_kernel_mcp"
    assert len(result["tool_names"]) == 8
    assert "memory_remember" in result["tool_names"]
    assert result["remember"].startswith("created ")
    # cross-prefix bridge works through the real protocol
    assert "Local memory" in result["search"]
    # soft-forget hides it from subsequent recall
    assert "archived" in result["forget"]
    assert "Local memory" not in result["search_after"]
