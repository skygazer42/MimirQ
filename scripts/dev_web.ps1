param(
  [switch]$Install
)

$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot

if ($Install -or -not (Test-Path (Join-Path $RepoRoot "web/node_modules"))) {
  Write-Host "[dev-web] pnpm install"
  pnpm -C web install
}

Write-Host "[dev-web] pnpm dev"
pnpm -C web dev

