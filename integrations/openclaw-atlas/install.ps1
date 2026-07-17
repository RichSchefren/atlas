$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Package = Join-Path $Root "atlas-memory-openclaw-0.2.0.tgz"
if (-not (Get-Command openclaw -ErrorAction SilentlyContinue)) { throw "openclaw is required" }
if (-not (Get-Command python -ErrorAction SilentlyContinue)) { throw "Python 3 is required" }
$Expected = (Get-Content (Join-Path $Root "CHECKSUMS.sha256")).Split()[0].ToLowerInvariant()
$Actual = (Get-FileHash $Package -Algorithm SHA256).Hash.ToLowerInvariant()
if ($Actual -ne $Expected) { throw "Atlas package checksum mismatch" }
openclaw plugins install $Package --force
openclaw config set plugins.slots.memory atlas-memory
openclaw plugins inspect atlas-memory --runtime --json
Write-Host "Atlas cognitive memory installed. Restart the OpenClaw gateway."
