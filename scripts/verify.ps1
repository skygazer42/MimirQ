param(
  [switch]$SkipTests,
  [switch]$SkipWeb,
  [switch]$SkipLintPy,
  [switch]$RunOpenApiCheck
)

$ErrorActionPreference = "Stop"

# Ensure we run from repo root so relative paths match the Makefile behaviour.
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot

Write-Host "[verify] Repo: $RepoRoot"

function Assert-VerificationSucceeded([string]$Name) {
  if ($LASTEXITCODE -ne 0) {
    throw "[verify] $Name failed with exit code $LASTEXITCODE"
  }
}

if (-not $SkipLintPy) {
  Write-Host "[verify] Ruff (lint)"
  python -m ruff check app tests scripts main.py
  Assert-VerificationSucceeded "Ruff"
} else {
  Write-Host "[verify] Skip: ruff"
}

Write-Host "[verify] Python compileall"
python -m compileall -q app scripts tests main.py
Assert-VerificationSucceeded "Python compilation"

if (-not $SkipTests) {
  Write-Host "[verify] Pytest"
  python -m pytest -q
  Assert-VerificationSucceeded "Pytest"
} else {
  Write-Host "[verify] Skip: tests"
}

if (-not $SkipWeb) {
  if ($RunOpenApiCheck) {
    Write-Host "[verify] OpenAPI export/types + check"
    pnpm -C web run openapi-types
    Assert-VerificationSucceeded "OpenAPI generation"
    python scripts/openapi_check.py
    Assert-VerificationSucceeded "OpenAPI check"
  }

  Write-Host "[verify] Web API checks"
  node web/scripts/check-api-contract.mjs
  Assert-VerificationSucceeded "API contract"
  node web/scripts/check-api-coverage.mjs
  Assert-VerificationSucceeded "API coverage"

  Write-Host "[verify] Web lint / ui-check / typecheck"
  pnpm -C web run lint
  Assert-VerificationSucceeded "Web lint"
  pnpm -C web run ui-check
  Assert-VerificationSucceeded "Web UI checks"
  pnpm -C web run typecheck
  Assert-VerificationSucceeded "TypeScript"
} else {
  Write-Host "[verify] Skip: web"
}

Write-Host "[verify] OK"
