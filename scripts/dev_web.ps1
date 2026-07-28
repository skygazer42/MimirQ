param(
  [switch]$Install
)

$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$WebRoot = Join-Path $RepoRoot "web"
Set-Location $WebRoot

if ($Install -or -not (Test-Path (Join-Path $RepoRoot "web/node_modules"))) {
  Write-Host "[dev-web] pnpm install"
  pnpm install
}

Write-Host "[dev-web] pnpm dev"
pnpm dev
