$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Package = Join-Path $Root "atlas-memory-gbrain-0.1.0.tgz"
if (-not (Get-Command node -ErrorAction SilentlyContinue)) { throw "Node.js is required" }
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { throw "npm is required" }
if (-not (Get-Command python -ErrorAction SilentlyContinue)) { throw "Python 3 is required" }
$Expected = (Get-Content (Join-Path $Root "CHECKSUMS.sha256")).Split()[0].ToLowerInvariant()
$Actual = (Get-FileHash $Package -Algorithm SHA256).Hash.ToLowerInvariant()
if ($Actual -ne $Expected) { throw "Atlas package checksum mismatch" }
npm install --global $Package
Write-Host "Atlas for GBrain installed. Run: atlas-gbrain status"
