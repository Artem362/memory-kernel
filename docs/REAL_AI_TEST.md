# Testing Memory Kernel on a real AI

This guide walks through connecting the Memory Kernel MCP server to a real LLM
client and verifying, by hand, that the AI can save and recall memories.

There are two layers of automated proof already:

- `tests/test_mcp.py` — calls each tool function directly.
- `tests/test_mcp_e2e.py` and `scripts/mcp_smoke.py` — drive the server as a
  subprocess over the **real MCP protocol** (initialize, tools/list, tools/call),
  exactly as an LLM client does. Run the live smoke test any time:

  ```powershell
  python scripts/mcp_smoke.py
  ```

The steps below add the final layer: a real model deciding when to call the tools.

## 1. Install with the MCP extra

```powershell
pip install -e .[mcp]
# or, from PyPI once released:
# pip install "amormorri-memory-kernel[mcp]"
```

Confirm the server starts and speaks the protocol:

```powershell
python scripts/mcp_smoke.py
```

## 2. Connect a client

### Claude Code (this repo)

A project-scoped [`.mcp.json`](../.mcp.json) is already included:

```json
{
  "mcpServers": {
    "memory-kernel": {
      "command": "memory-kernel-mcp",
      "args": ["--db", ".memory-kernel/memory.db"],
      "env": { "PYTHONIOENCODING": "utf-8" }
    }
  }
}
```

Start a **new** Claude Code session in this folder and approve the `memory-kernel`
server when prompted. (A running session will not pick up a new server mid-flight.)
Check it is connected with the `/mcp` command.

### Claude Desktop

Edit `claude_desktop_config.json` (Settings → Developer → Edit Config):

```json
{
  "mcpServers": {
    "memory-kernel": {
      "command": "memory-kernel-mcp",
      "env": {
        "MEMORY_KERNEL_DB": "C:\\Users\\you\\.memory-kernel\\memory.db",
        "PYTHONIOENCODING": "utf-8"
      }
    }
  }
}
```

Restart Claude Desktop. The tools appear under the connection (plug) icon.

## 3. Test script for the model

Give the AI these prompts in order and watch which tools it calls. Expected
behaviour is noted under each.

1. **"Запамʼятай: ми вирішили тримати памʼять локально у SQLite, без хмари."**
   → calls `memory_remember` (kind=decision). Should report `created <id>`.

2. **"Запамʼятай цей шматок нотаток: треба додати експорт у Markdown; памʼять
   має лишатись дешевою; користувач надає перевагу точному пошуку."**
   → calls `memory_ingest`. Should create ~3 memories with inferred kinds
   (task / constraint / preference).

3. **"Що ми вирішували щодо памʼяті?"**
   → calls `memory_search` with a query like "памʼять рішення". Should return
   the decision from step 1 — note the query word form differs from what was
   stored ("памʼяті" vs "памʼять"), which the stemmer bridges.

4. **"Збери короткий контекст по нашому проєкту, бюджет 600 символів."**
   → calls `memory_build_context`. Should return a packed block within budget,
   without near-duplicate entries.

5. **"Та нотатка про експорт у Markdown більше не актуальна, забудь її."**
   → calls `memory_forget` with the right id (it may `memory_search` or
   `memory_list` first to find it). Should report `archived <id>`.

6. **"Покажи статистику памʼяті."**
   → calls `memory_stats`. Should show totals and the per-kind breakdown.

## 4. What to look for

- The model picks the **right tool** from the flat schema without you naming it.
- Ukrainian queries find memories saved in a different case/form.
- `memory_forget` hides a memory from later searches, and you can still recover
  it from the CLI: `memory-kernel restore --id <id>`.
- Destructive edits are **not** offered to the model — there is no delete/update
  tool. That is by design.

## 5. Inspect from the CLI in parallel

While the AI works, watch the same database from a terminal:

```powershell
memory-kernel list
memory-kernel list --include-archived
memory-kernel stats --since 1d
memory-kernel verify
```

Everything the AI saved is plain, inspectable rows — no black box.
