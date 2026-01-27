param(
  [string]$Host = "0.0.0.0",
  [int]$Port = 8000,
  [switch]$NoReload,
  [switch]$SkipWeb,
  [switch]$InstallWeb
)

$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot

if (-not $SkipWeb) {
  $webScript = Join-Path $RepoRoot "scripts/dev_web.ps1"
  $webArgs = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", $webScript
  )
  if ($InstallWeb) {
    $webArgs += "-Install"
  }

  Write-Host "[dev] starting web in a new PowerShell window (InstallWeb=$InstallWeb)"
  Start-Process -FilePath "powershell" -ArgumentList $webArgs -WorkingDirectory $RepoRoot | Out-Null
} else {
  Write-Host "[dev] Skip: web"
}

Write-Host "[dev] starting backend (host=$Host port=$Port reload=$(-not $NoReload))"
& (Join-Path $RepoRoot "scripts/dev_backend.ps1") -Host $Host -Port $Port -NoReload:$NoReload

