$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot

function Require-Cmd([string]$Name) {
  $cmd = Get-Command $Name -ErrorAction SilentlyContinue
  if (-not $cmd) {
    throw "Missing required command: $Name"
  }
}

Require-Cmd 'node'
Require-Cmd 'pnpm'

$python = 'python'
$venvPython = Join-Path $repoRoot '.venv\Scripts\python.exe'
if (Test-Path $venvPython) {
  $python = $venvPython
} else {
  Require-Cmd 'python'
}

Push-Location $repoRoot
try {
  Write-Host "[verify] python lint (ruff)"
  & $python -m ruff check app tests scripts main.py

  Write-Host "[verify] api contract (web -> backend routes)"
  node scripts/check-api-contract.mjs

  Push-Location (Join-Path $repoRoot 'web')
  try {
    if (!(Test-Path 'node_modules')) {
      Write-Host "[verify] installing web deps (pnpm install)"
      pnpm install --frozen-lockfile
    }
    Write-Host "[verify] web lint"
    pnpm run lint
    Write-Host "[verify] web typecheck"
    pnpm run typecheck
  } finally {
    Pop-Location
  }

  $env:PYTHONPYCACHEPREFIX = Join-Path $repoRoot '.pycache'
  Write-Host "[verify] python compileall"
  & $python -m compileall -q app

  Write-Host "[verify] OK"
} finally {
  Pop-Location
}
