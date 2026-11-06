param(
  [Alias("Host")]
  [string]$BackendHost = "0.0.0.0",
  [int]$Port = 8000,
  [switch]$NoReload
)

$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot

$env:HOST = $BackendHost
$env:PORT = "$Port"
if ($NoReload) {
  $env:UVICORN_RELOAD = "false"
}

Write-Host "[dev-backend] host=$BackendHost port=$Port reload=$(-not $NoReload)"
python main.py

