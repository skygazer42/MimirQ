param(
  [string]$Host = "0.0.0.0",
  [int]$Port = 8000,
  [switch]$NoReload,
  [switch]$SkipWeb,
  [switch]$InstallWeb
)

$ErrorActionPreference = "Stop"

Write-Host "[dev] NOTE: scripts/dev.ps1 is deprecated; use scripts/dev_all.ps1 instead."

& (Join-Path $PSScriptRoot "dev_all.ps1") @PSBoundParameters
