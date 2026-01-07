$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot

function Ensure-Copy([string]$Source, [string]$Dest) {
  $srcPath = Join-Path $repoRoot $Source
  $dstPath = Join-Path $repoRoot $Dest

  if (!(Test-Path $srcPath)) {
    throw "Missing template file: $Source"
  }

  if (Test-Path $dstPath) {
    Write-Host "[env] exists: $Dest"
    return
  }

  $dstDir = Split-Path -Parent $dstPath
  if ($dstDir -and !(Test-Path $dstDir)) {
    New-Item -ItemType Directory -Force -Path $dstDir | Out-Null
  }

  Copy-Item -Force $srcPath $dstPath
  Write-Host "[env] created: $Dest"
}

Push-Location $repoRoot
try {
  Ensure-Copy '.env.example' '.env'
  Ensure-Copy 'web/.env.local.example' 'web/.env.local'
  Write-Host "[env] done"
} finally {
  Pop-Location
}

