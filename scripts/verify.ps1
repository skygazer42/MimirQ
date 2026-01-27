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

if (-not $SkipLintPy) {
  Write-Host "[verify] Ruff (lint)"
  python -m ruff check app tests scripts main.py
} else {
  Write-Host "[verify] Skip: ruff"
}

Write-Host "[verify] Python compileall"
python -m compileall -q app scripts tests main.py

if (-not $SkipTests) {
  Write-Host "[verify] Pytest"
  python -m pytest -q
} else {
  Write-Host "[verify] Skip: tests"
}

if (-not $SkipWeb) {
  if ($RunOpenApiCheck) {
    Write-Host "[verify] OpenAPI export/types + check"
    pnpm -C web run openapi-types
    python scripts/openapi_check.py
  }

  Write-Host "[verify] Web API checks"
  node web/scripts/check-api-contract.mjs
  node web/scripts/check-api-coverage.mjs

  Write-Host "[verify] Web lint / ui-check / typecheck"
  pnpm -C web run lint
  pnpm -C web run ui-check
  pnpm -C web run typecheck
} else {
  Write-Host "[verify] Skip: web"
}

Write-Host "[verify] OK"
