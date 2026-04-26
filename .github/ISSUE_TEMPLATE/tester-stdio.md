---
name: Tester report — Claude Code MCP adapter (stdio bridge)
about: The MCP wire-level subprocess test failed, or live Claude Code can't connect
labels: tester-finding, claude-code, mcp
---

## Tester

<!-- Your name + setup -->

## Failure mode

- [ ] `pytest tests/integration/test_claude_code_stdio.py` red
- [ ] Claude Code can't find the `atlas` MCP server
- [ ] Claude Code finds it but `tools/list` returns 0 tools
- [ ] A specific tool call fails (which?)
- [ ] Subprocess hangs / never responds to initialize
- [ ] Stderr full of stack traces
- [ ] Other

## What you tried

```bash
# Pytest path
PYTHONPATH=. pytest tests/integration/test_claude_code_stdio.py -v

# OR live Claude Code path — paste your ~/.claude/.mcp.json snippet:
```

```json
{
  "mcpServers": {
    "atlas": { ... }
  }
}
```

## stderr / pytest output

```
Paste failure trace here.
```

## Environment

- Atlas commit: `git rev-parse HEAD`
- `python --version`:
- Claude Code version (if applicable): `claude --version`
- Neo4j reachable: `curl http://localhost:7474` (paste status)
