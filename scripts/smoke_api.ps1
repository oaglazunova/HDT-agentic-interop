# To run (in PowerShell): powershell -NoProfile -ExecutionPolicy Bypass -File scripts\smoke_api.ps1
Param(
  [string]$ApiUrl = $env:HDT_API_BASE,
  [int]$UserId = $(if ($env:SMOKE_USER_ID) { [int]$env:SMOKE_USER_ID } else { 3 })
)

$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($ApiUrl)) { $ApiUrl = "http://localhost:5000" }
$ApiUrl = $ApiUrl.TrimEnd('/')

# Match bash fallback: use env MODEL_DEVELOPER_1_API_KEY, else 'MODEL_DEVELOPER_1'
$apiKey = $env:MODEL_DEVELOPER_1_API_KEY
if ([string]::IsNullOrWhiteSpace($apiKey)) { $apiKey = 'MODEL_DEVELOPER_1' }

# Canonical header: use Authorization: Bearer
$headers = @{
  Authorization = "Bearer $apiKey"
}

Write-Host "→ GET $ApiUrl/healthz"
$health = Invoke-RestMethod -Uri "$ApiUrl/healthz" -Headers $headers -Method GET -TimeoutSec 10
if ($health.status -ne 'ok') { throw "healthz failed: $($health | ConvertTo-Json -Depth 5)" }
Write-Host "✔ healthz ok"

Write-Host "→ GET $ApiUrl/get_walk_data?user_id=$UserId"
$resp = Invoke-RestMethod -Uri "$ApiUrl/get_walk_data?user_id=$UserId" -Headers $headers -Method GET -TimeoutSec 20

# Response may be array-of-envelopes or a single object; normalize.
$entry = $null
if ($resp -is [System.Array]) {
  $entry = $resp | Where-Object { $_.user_id -eq $UserId } | Select-Object -First 1
} else {
  $entry = $resp
}

if (-not $entry) { throw "No envelope for user $UserId: $($resp | ConvertTo-Json -Depth 6)" }

if ($entry.error) {
  Write-Warning "API returned error for user $UserId: $($entry.error)"
} elseif (-not $entry.data -and -not $entry.records) {
  throw "No data/records in response for user $UserId: $($entry | ConvertTo-Json -Depth 6)"
}

Write-Host "✔ get_walk_data ok for user $UserId"
exit 0
