# Atlas cognitive memory for GBrain

`@atlas-memory/gbrain` is an independently installable bridge between GBrain's
public MCP contract and Atlas's AGM/Ripple cognitive service. It is not a
GBrain plugin that pretends to add tools: GBrain's plugin-v1 contract cannot
declare tools. The `atlas-gbrain` CLI calls real `get_page`, `put_page`,
`search`, and `get_brain_identity` operations over GBrain MCP, then links each
page to an Atlas cognitive identity.

GBrain remains the markdown/page system of record. Atlas adds immutable
revision lineage, confidence, dependencies, audit history, and Ripple
reassessment. Atlas adds no Neo4j, Docker, embedding provider, or API-key
requirement. It uses Python's standard library and a private local SQLite
database.

## Requirements

- Node.js 22.22.3, 24.15+, or 25.9+
- Python 3.10+
- either a working local `gbrain serve` command or a GBrain HTTP MCP URL and
  access token

The protected contract fixture is GBrain `0.42.61.0` at commit
`26d2f8abfc0e7c6fead5ea89b6494ce8c3cf737f`.

## Install

Verify and install the committed release artifact:

```bash
shasum -a 256 -c CHECKSUMS.sha256
npm install --global ./atlas-memory-gbrain-0.1.0.tgz
atlas-gbrain status
```

On Windows PowerShell:

```powershell
Get-FileHash .\atlas-memory-gbrain-0.1.0.tgz -Algorithm SHA256
npm install --global .\atlas-memory-gbrain-0.1.0.tgz
atlas-gbrain status
```

For a nonstandard local launch, set `GBRAIN_COMMAND`, `GBRAIN_ARGS` (a JSON
string array), and optionally `GBRAIN_CWD`. For a remote server, set
`GBRAIN_MCP_URL` and `GBRAIN_MCP_TOKEN`. `--gbrain-*` flags override the
environment. Set `GBRAIN_ATLAS_BRAIN_ID` (or pass `--brain-id`) when the target
is not the default `host` brain, and `GBRAIN_SOURCE` for a non-default source.
For local stdio, the bridge passes that brain id to GBrain as
`GBRAIN_BRAIN_ID`, so it selects the actual mounted database as well as the
Atlas identity. For remote MCP, the URL already selects a single served brain;
the supplied brain id is its explicit Atlas identity label and cannot reroute
an HTTP request to a different database.

## Use

```bash
atlas-gbrain put --slug plans/launch --file launch.md --confidence-ppm 900000
atlas-gbrain sync --slug plans/launch
atlas-gbrain get --slug plans/launch
atlas-gbrain search --query "launch evidence" --limit 10
atlas-gbrain audit --slug plans/launch
```

Declare a cognitive dependency after both pages have been synchronized:

```bash
atlas-gbrain depend \
  --dependent-slug plans/campaign \
  --support-slug plans/launch \
  --strength-ppm 1000000
```

The next `put` or `sync` that changes `plans/launch` appends an immutable Atlas
revision and returns any Ripple reassessment proposals for `plans/campaign`.

`atlas-gbrain forget --slug ...` deprecates only the linked Atlas cognitive
record and retains its audit lineage. It deliberately preserves the GBrain
page. GBrain deletion remains a separate, explicit GBrain operation.

## Identity and trust boundary

The stable Atlas id is a hash of GBrain brain id, source id, and slug. Brain
and source are separate tenancy axes; the bridge never collapses them.
Cross-source cognitive dependencies are refused because they require explicit
federation policy. Remote MCP calls keep GBrain's own OAuth/source rules and
server-stamped provenance.

A `put` writes GBrain first because markdown is authoritative. If the later
Atlas synchronization fails, the command exits nonzero and prints the exact
recovery command: rerun `atlas-gbrain sync --slug ...`. It never reports a
two-system success after only one side commits.

## Verification

```bash
npm ci
npm test
npm pack
```

The package test drives a real MCP subprocess and the bundled Atlas service
through page creation, dependency declaration, revision, Ripple, restart
persistence, search, audit, and forget. Protected CI additionally installs the
package-only tarball and exercises the pinned GBrain `serve` lifecycle on
Ubuntu PGLite. Windows runs the same bridge/service package test. PGLite is not
used on macOS 26 Apple Silicon because the pinned upstream GBrain release marks
that combination incompatible; local GBrain may use native Postgres there.
