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

  Copy-Item -Force $srcPath $dstPath
  Write-Host "[env] created: $Dest"
}

Push-Location $repoRoot
try {
  Ensure-Copy '.env.prod.example' '.env'
  Write-Host "[env] production template applied"
} finally {
  Pop-Location
}

