#!/usr/bin/env python3
"""End-to-end smoke test of the Memory Kernel MCP server over the real protocol.

Launches the server as a subprocess and drives it with the actual MCP client
(stdio transport, JSON-RPC) exactly as an LLM client (Claude Desktop, Claude
Code, ...) would. This exercises the wire protocol — initialize handshake,
tools/list, tools/call — not just the Python tool functions.

Run:  python scripts/mcp_smoke.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


def _text(result) -> str:
    parts = []
    for block in result.content:
        parts.append(getattr(block, "text", ""))
    return "\n".join(parts)


async def main() -> int:
    tmp = Path(tempfile.mkdtemp()) / "mcp_smoke.db"
    env = {
        **os.environ,
        "PYTHONPATH": str(SRC),
        "PYTHONIOENCODING": "utf-8",
    }
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "memory_kernel.mcp_server", "--db", str(tmp)],
        env=env,
    )

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            print(f"[handshake] connected to: {init.serverInfo.name} v{init.serverInfo.version}")

            tools = await session.list_tools()
            print(f"[tools/list] {len(tools.tools)} tools: {', '.join(t.name for t in tools.tools)}")

            print("\n[tools/call memory_remember]")
            r = await session.call_tool(
                "memory_remember",
                {
                    "scope": "demo",
                    "kind": "decision",
                    "title": "Памʼять локальна",
                    "content": "Вирішили тримати памʼять локально у SQLite.",
                    "tags": ["памʼять", "sqlite"],
                },
            )
            print(" ", _text(r))

            print("\n[tools/call memory_ingest]")
            r = await session.call_tool(
                "memory_ingest",
                {"text": "Треба додати MCP. Памʼяттю керує агент.", "scope": "demo"},
            )
            print(" ", _text(r).replace("\n", "\n  "))

            print("\n[tools/call memory_search query='рішення' (cross-prefix bridge)]")
            r = await session.call_tool("memory_search", {"query": "рішення", "limit": 3})
            print(" ", _text(r).replace("\n", "\n  "))

            print("\n[tools/call memory_search query='памʼяттю' (declension bridge)]")
            r = await session.call_tool("memory_search", {"query": "памʼяттю", "limit": 3})
            found = "Памʼять локальна" in _text(r) or "памʼят" in _text(r).lower()
            print(f"  declension form matched stored 'памʼять': {found}")

            print("\n[tools/call memory_stats]")
            r = await session.call_tool("memory_stats", {})
            print(" ", _text(r).replace("\n", "\n  "))

    print("\nOK: full MCP protocol round-trip succeeded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
