# Atlas — MCP Plugin Registry submission

Files in this directory are intended for submission to the official
MCP plugin registry once it ships. Until then, `atlas.json` doubles
as a one-file install manifest users can drop into Claude Code's
`~/.claude/.mcp.json` after path substitution.

## What's here

- `atlas.json` — the canonical plugin manifest (13 tools, stdio
  transport, prerequisites, install command).

## Submission

When the MCP registry opens for submissions:

```bash
# Pseudo-code — actual command depends on the registry CLI
mcp-registry submit mcp-registry/atlas.json
```

Until then:

1. User clones https://github.com/RichSchefren/atlas
2. User runs `pip install -e .` in the repo
3. User pastes the `install.stdio` block from `atlas.json` into
   their `~/.claude/.mcp.json` under `mcpServers.atlas`
4. Restart Claude Code
5. Type `/mcp` — atlas should appear with 13 tools

## Versioning

Bump `version` in `atlas.json` on every Atlas release. The MCP
registry tracks per-version availability so users can pin.
