param(
  [string]$BaseUrl = "http://localhost:8000/api/v1",
  [string]$Identifier = $env:MIMIRQ_DEMO_IDENTIFIER,
  [string]$Password = $env:MIMIRQ_DEMO_PASSWORD,
  [string]$Token = $env:MIMIRQ_DEMO_TOKEN,
  [string]$DatasetName = "",
  [string]$FilePath = "",
  [string]$ParserBackend = "auto",
  [int]$TimeoutSec = 600,
  [int]$PollIntervalSec = 2,
  [string]$GovernanceProfileRef = "builtin:html_web",
  [switch]$DryRun
)

$ErrorActionPreference = "Stop"

# Ensure we run from repo root so relative paths resolve predictably.
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot

function Write-Step([string]$Msg) {
  Write-Host ""
  Write-Host ("[demo] " + $Msg)
}

function New-JsonHeaders([string]$BearerToken) {
  $h = New-Object "System.Collections.Generic.Dictionary[[String],[String]]"
  $h.Add("Accept", "application/json")
  if ($BearerToken) {
    $h.Add("Authorization", ("Bearer " + $BearerToken))
  }
  return $h
}

function Get-AccessToken {
  param(
    [string]$BaseUrl,
    [string]$Identifier,
    [string]$Password
  )

  if (-not $Identifier -or -not $Password) {
    throw "Missing auth. Provide -Token or set -Identifier/-Password (or env: MIMIRQ_DEMO_IDENTIFIER / MIMIRQ_DEMO_PASSWORD)."
  }

  $body = @{ identifier = $Identifier; password = $Password } | ConvertTo-Json -Compress
  $resp = Invoke-RestMethod -Method Post -Uri ("$BaseUrl/auth/login") -Headers (New-JsonHeaders "") -ContentType "application/json" -Body $body
  $access = $resp.token.access_token
  if (-not $access) {
    throw "Login response did not include token.access_token"
  }
  return [string]$access
}

function New-HttpClient([string]$BearerToken) {
  $client = New-Object System.Net.Http.HttpClient
  $client.Timeout = [TimeSpan]::FromMinutes(20)
  if ($BearerToken) {
    $client.DefaultRequestHeaders.Authorization = New-Object System.Net.Http.Headers.AuthenticationHeaderValue("Bearer", $BearerToken)
  }
  return $client
}

function HttpClient-PostMultipart {
  param(
    [System.Net.Http.HttpClient]$Client,
    [string]$Url,
    [string]$FilePath,
    [hashtable]$Fields
  )

  $mp = New-Object System.Net.Http.MultipartFormDataContent

  foreach ($k in $Fields.Keys) {
    $mp.Add([System.Net.Http.StringContent]::new([string]$Fields[$k]), [string]$k)
  }

  $stream = [System.IO.File]::OpenRead($FilePath)
  try {
    $fileName = [System.IO.Path]::GetFileName($FilePath)
    $fileContent = New-Object System.Net.Http.StreamContent($stream)
    $fileContent.Headers.ContentType = [System.Net.Http.Headers.MediaTypeHeaderValue]::Parse("application/octet-stream")
    $mp.Add($fileContent, "file", $fileName)

    $resp = $Client.PostAsync($Url, $mp).GetAwaiter().GetResult()
    $text = $resp.Content.ReadAsStringAsync().GetAwaiter().GetResult()
    if (-not $resp.IsSuccessStatusCode) {
      throw ("HTTP " + [int]$resp.StatusCode + " POST " + $Url + "`n" + $text)
    }
    return $text | ConvertFrom-Json
  } finally {
    $stream.Dispose()
  }
}

function HttpClient-GetBytes {
  param(
    [System.Net.Http.HttpClient]$Client,
    [string]$Url
  )
  $resp = $Client.GetAsync($Url).GetAwaiter().GetResult()
  $bytes = $resp.Content.ReadAsByteArrayAsync().GetAwaiter().GetResult()
  if (-not $resp.IsSuccessStatusCode) {
    $text = [System.Text.Encoding]::UTF8.GetString($bytes)
    throw ("HTTP " + [int]$resp.StatusCode + " GET " + $Url + "`n" + $text)
  }
  return ,$bytes
}

if (-not $FilePath) {
  $FilePath = Join-Path $RepoRoot "README.md"
}
$FileAbs = Resolve-Path $FilePath

if (-not $DatasetName) {
  $DatasetName = "demo-" + (Get-Date -Format "yyyyMMdd-HHmmss")
}

Write-Step "Target API: $BaseUrl"
Write-Step "Demo file: $FileAbs"

if ($DryRun) {
  Write-Host "[demo] DryRun=ON (no network calls will be made)"
  Write-Host ("[demo] dataset_name=" + $DatasetName)
  Write-Host ("[demo] parser_backend=" + $ParserBackend)
  Write-Host ("[demo] governance_profile_ref=" + $GovernanceProfileRef)
  exit 0
}

if (-not $Token) {
  Write-Step "Login..."
  $Token = Get-AccessToken -BaseUrl $BaseUrl -Identifier $Identifier -Password $Password
}

$headers = New-JsonHeaders $Token
$client = New-HttpClient $Token

try {
  Write-Step ("Create dataset: " + $DatasetName)
  $datasetBody = @{ name = $DatasetName; description = "demo (scripted) ingestion flow" } | ConvertTo-Json -Compress
  $dataset = Invoke-RestMethod -Method Post -Uri ("$BaseUrl/datasets/") -Headers $headers -ContentType "application/json" -Body $datasetBody
  $datasetId = [string]$dataset.id
  if (-not $datasetId) { throw "Dataset create response missing id" }

  Write-Step ("Upload document to dataset_id=" + $datasetId)
  $upload = HttpClient-PostMultipart -Client $client -Url ("$BaseUrl/documents/upload") -FilePath $FileAbs -Fields @{
    dataset_id = $datasetId
    parser_backend = $ParserBackend
  }
  $docId = [string]$upload.id
  if (-not $docId) { throw "Upload response missing id" }
  Write-Host ("[demo] document_id=" + $docId + " status=" + $upload.status)

  Write-Step "Poll document status..."
  $deadline = (Get-Date).AddSeconds([int]$TimeoutSec)
  while ($true) {
    if ((Get-Date) -gt $deadline) {
      throw ("Timeout waiting for document completion (timeout_sec=" + $TimeoutSec + ")")
    }
    $st = Invoke-RestMethod -Method Get -Uri ("$BaseUrl/documents/$docId/status") -Headers $headers
    $status = [string]$st.status
    $progress = $st.processing_progress
    $stage = [string]$st.current_stage
    Write-Host ("[demo] status=" + $status + " progress=" + $progress + " stage=" + $stage)

    if ($status -eq "completed") { break }
    if ($status -eq "failed") {
      throw ("Document failed: " + ($st.error_message | Out-String))
    }
    Start-Sleep -Seconds ([int]$PollIntervalSec)
  }

  Write-Step "Fetch document detail (includes pipeline provenance / analytics when enabled)"
  $doc = Invoke-RestMethod -Method Get -Uri ("$BaseUrl/documents/$docId") -Headers $headers
  Write-Host ("[demo] filename=" + [string]$doc.filename)
  Write-Host ("[demo] parser_backend=" + [string]$doc.parser_backend)

  Write-Step "Export ingestion policy snippet from a governance profile (best-effort)"
  $outDir = Join-Path $RepoRoot "runs/demo"
  New-Item -ItemType Directory -Force -Path $outDir | Out-Null
  $policyBytes = HttpClient-GetBytes -Client $client -Url ("$BaseUrl/pipeline/governance-profiles/$GovernanceProfileRef/export-ingestion-policy")
  $safeKey = ([string]$GovernanceProfileRef).Trim() -replace '[^a-zA-Z0-9_.-]+', '_' 
  if (-not $safeKey) { $safeKey = "profile" }
  $outFile = Join-Path $outDir ($safeKey + ".ingestion_policy.json")
  [System.IO.File]::WriteAllBytes($outFile, $policyBytes)
  Write-Host ("[demo] saved: " + $outFile)

  Write-Host ""
  Write-Host "[demo] DONE"
  Write-Host ("[demo] dataset_id=" + $datasetId)
  Write-Host ("[demo] document_id=" + $docId)
} finally {
  $client.Dispose()
}
