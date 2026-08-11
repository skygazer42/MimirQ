param(
  [switch]$SkipPython,
  [switch]$SkipWeb,
  [switch]$SkipDocs
)

$ErrorActionPreference = "Stop"

# Ensure we run from repo root so relative paths match the Makefile behaviour.
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot

Write-Host "[audit] Repo: $RepoRoot"

function Assert-AuditSucceeded([string]$Name) {
  if ($LASTEXITCODE -ne 0) {
    throw "[audit] $Name failed with exit code $LASTEXITCODE"
  }
}

if (-not $SkipPython) {
  Write-Host "[audit] Python (pip-audit)"
  python -m pip_audit -r requirements.txt `
    --ignore-vuln PYSEC-2026-311 `
    --ignore-vuln PYSEC-2026-3046 `
    --ignore-vuln PYSEC-2026-2447 `
    --ignore-vuln PYSEC-2026-1325
  Assert-AuditSucceeded "Python"
} else {
  Write-Host "[audit] Skip: python"
}

if (-not $SkipWeb) {
  Write-Host "[audit] Web (pnpm audit)"
  pnpm -C web audit --prod --audit-level high
  Assert-AuditSucceeded "Web production dependencies"
  pnpm -C web audit --audit-level high
  Assert-AuditSucceeded "Web complete dependency tree"
} else {
  Write-Host "[audit] Skip: web"
}

if (-not $SkipDocs) {
  Write-Host "[audit] Handbook (npm audit)"
  npm --prefix docs-site audit --audit-level=high --json | python scripts/check_npm_audit.py
  Assert-AuditSucceeded "Handbook complete dependency tree"
} else {
  Write-Host "[audit] Skip: handbook"
}

Write-Host "[audit] OK"
