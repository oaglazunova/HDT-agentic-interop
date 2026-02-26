Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$catalogPath = Join-Path $repoRoot "demo\scenarios\obesitycoach_daily_profile\vault_catalog.json"
$outDir = Join-Path $repoRoot "artifacts\demo_mapping_negotiation"

Write-Host "=== Mapping-plan negotiation demo ===" -ForegroundColor Cyan
Write-Host "Catalog: $catalogPath"
Write-Host "Output:  $outDir"
Write-Host ""

python -m hdt_a2a.host.run_negotiation `
  --user-url http://localhost:9200/ `
  --provider-url http://localhost:9100/ `
  --algo-id provider.obesityCoach `
  --algo-version 0.1.0 `
  --vault-catalog $catalogPath `
  --out-dir $outDir

if ($LASTEXITCODE -ne 0) {
    throw "Demo negotiation failed."
}

$latestRun = Get-ChildItem $outDir -Filter *.run.json |
    Sort-Object LastWriteTimeUtc -Descending |
    Select-Object -First 1

if (-not $latestRun) {
    throw "No run manifest found in $outDir"
}

$run = Get-Content $latestRun.FullName -Raw | ConvertFrom-Json
$plan = Get-Content $run.plan_path -Raw | ConvertFrom-Json

Write-Host ""
Write-Host "=== Demo summary ===" -ForegroundColor Green
Write-Host "Plan ID:      $($run.plan_id)"
if ($run.PSObject.Properties.Name -contains "plan_id_source") {
    Write-Host "Plan ID src:  $($run.plan_id_source)"
}
Write-Host "Iterations:   $($run.user_agent.iterations)"
Write-Host "Dataset:      $($plan.dataset.dataset_id)"
Write-Host "Table:        $($plan.dataset.table_name)"
Write-Host "Columns:      $([string]::Join(', ', $plan.required_columns))"
Write-Host ""
Write-Host "Artifacts:"
Write-Host "  Plan:       $($run.plan_path)"
Write-Host "  Run report: $($latestRun.FullName)"
Write-Host ""

Write-Host "Record mapping summary:" -ForegroundColor Yellow
$plan.record_mapping.PSObject.Properties |
    Sort-Object Name |
    ForEach-Object {
        $ptr = $_.Name
        $expr = $_.Value
        if ($expr.op -eq "column") {
            Write-Host ("  {0}  <=  column({1})" -f $ptr, $expr.name)
        }
        elseif ($expr.op -eq "parse_date") {
            $arg0 = $expr.args[0]
            Write-Host ("  {0}  <=  parse_date(column({1}), {2})" -f $ptr, $arg0.name, $expr.format)
        }
        else {
            Write-Host ("  {0}  <=  {1}" -f $ptr, ($expr | ConvertTo-Json -Compress))
        }
    }