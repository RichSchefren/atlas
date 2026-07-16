param(
    [switch]$NoActivate
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$HermesHome = if ($env:HERMES_HOME) { $env:HERMES_HOME } else { Join-Path $HOME ".hermes" }
$Destination = Join-Path $HermesHome "plugins\atlas"

New-Item -ItemType Directory -Path $Destination -Force | Out-Null
Copy-Item (Join-Path $ScriptDir "atlas\__init__.py") (Join-Path $Destination "__init__.py") -Force
Copy-Item (Join-Path $ScriptDir "atlas\store.py") (Join-Path $Destination "store.py") -Force
Copy-Item (Join-Path $ScriptDir "plugin.yaml") (Join-Path $Destination "plugin.yaml") -Force

Write-Host "Installed Atlas Hermes provider at $Destination"

if (-not $NoActivate) {
    if (Get-Command hermes -ErrorAction SilentlyContinue) {
        hermes memory setup atlas
    } else {
        Write-Host "Hermes CLI is not on PATH. After installing Hermes, run: hermes memory setup atlas"
    }
}
