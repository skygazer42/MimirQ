param(
  [switch]$SkipPython,
  [switch]$SkipWeb
)

$ErrorActionPreference = "Stop"

# Ensure we run from repo root so relative paths match the Makefile behaviour.
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot

Write-Host "[audit] Repo: $RepoRoot"

if (-not $SkipPython) {
  Write-Host "[audit] Python (pip-audit)"
  pip-audit -r requirements.txt --no-deps --disable-pip
} else {
  Write-Host "[audit] Skip: python"
}

if (-not $SkipWeb) {
  Write-Host "[audit] Web (pnpm audit)"
  pnpm -C web audit --prod --audit-level high --ignore-registry-errors
} else {
  Write-Host "[audit] Skip: web"
}

Write-Host "[audit] OK"

