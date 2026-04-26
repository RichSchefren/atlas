# Security Policy

## Reporting a vulnerability

Email **rich@strategicprofits.com** with details. Do not file a public GitHub issue for security problems.

I aim to acknowledge within 48 hours and ship a fix within 14 days for verified issues. Coordinated disclosure: I'll work with you on a timeline before publishing.

## Scope

In scope:
- AGM correctness regressions (a postulate that was passing now fails)
- Ledger tamper-detection failures (a chain that should report `intact: false` reports `intact: true`)
- Trust-layer bypasses (a candidate reaches the ledger without satisfying the promotion policy)
- Sanitization gaps (untrusted input mutates Atlas state via a path that should sanitize)
- Adapter-level RCE (Claude Code MCP stdio, Hermes plugin, OpenClaw plugin)

Out of scope:
- Rate limiting (Atlas is local-first by design — DoS is not a threat model)
- Anything requiring already-compromised local-machine access
- Social engineering against the maintainer

## Supported versions

Atlas is alpha. Only the latest `master` is supported. There are no LTS branches.
