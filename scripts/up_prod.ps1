param(
  [switch]$Web
)

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot

Push-Location $repoRoot
try {
  & (Join-Path $repoRoot 'scripts/bootstrap_prod_env.ps1')

  if ($Web) {
    docker compose -f docker-compose.prod.yml --profile web up -d --build
  } else {
    docker compose -f docker-compose.prod.yml up -d --build
  }

  docker compose -f docker-compose.prod.yml ps
} finally {
  Pop-Location
}

