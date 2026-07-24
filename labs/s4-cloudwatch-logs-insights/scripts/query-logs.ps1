. "$PSScriptRoot/common.ps1"
$null = Assert-ExternalBinding
$evidence = Get-EvidenceDirectory
$window = Get-Content -LiteralPath (Join-Path $evidence "query-window.json") -Raw | ConvertFrom-Json
if ($window.region -cne $Region -or $window.log_group -cne $LogGroupName) { throw "Query window target mismatch." }
if (($window.end_epoch - $window.start_epoch) -le 0 -or ($window.end_epoch - $window.start_epoch) -gt 900) {
    throw "Query window must be positive and no more than 15 minutes."
}
$podName = Get-ExactJobPodName

function Convert-LogsInsightsRows {
    param([object[]]$Rows)
    foreach ($row in @($Rows)) {
        $fields = [ordered]@{}
        foreach ($cell in @($row)) {
            if ($cell.field -and $cell.field -cne "@ptr") {
                $fields[[string]$cell.field] = [string]$cell.value
            }
        }
        [pscustomobject]$fields
    }
}

function Invoke-BoundedQuery([string]$Name, [string]$QueryPath, [int]$ExpectedCount) {
    $query = Get-Content -LiteralPath $QueryPath -Raw
    $started = Get-AwsJson @(
        "logs", "start-query", "--region", $Region,
        "--log-group-name", $LogGroupName,
        "--start-time", "$($window.start_epoch)",
        "--end-time", "$($window.end_epoch)",
        "--query-string", $query
    )
    if (-not $started.queryId) { throw "StartQuery returned no query ID." }
    $result = $null
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Seconds 1
        $result = Get-AwsJson @("logs", "get-query-results", "--region", $Region, "--query-id", $started.queryId)
        if ($result.status -in @("Complete", "Failed", "Cancelled", "Timeout", "Unknown")) { break }
    }
    if ($result.status -cne "Complete") { throw "$Name query did not complete: $($result.status)" }
    $decoded = @(Convert-LogsInsightsRows -Rows @($result.results))
    if ($decoded.Count -ne $ExpectedCount) {
        throw "$Name query returned $($decoded.Count) rows; expected exactly $ExpectedCount."
    }
    foreach ($row in $decoded) {
        if ($row.namespace -cne $Namespace -or $row.pod -cne $podName) {
            throw "$Name query returned a row outside the exact runtime namespace/Pod."
        }
        if ($Name -ceq "errors" -and $row.level -cne "ERROR") {
            throw "errors query returned a non-ERROR row."
        }
    }
    [ordered]@{
        schema = "udemy4-s4-live-logs-insights-evidence-v1"
        name = $Name
        region = $Region
        log_group = $LogGroupName
        start_epoch = $window.start_epoch
        end_epoch = $window.end_epoch
        status = $result.status
        statistics = $result.statistics
        results = $result.results
        decoded_results = $decoded
    } | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath (Join-Path $evidence "$Name-results.json") -Encoding utf8NoBOM
}

Invoke-BoundedQuery "all-events" "$PSScriptRoot/../queries/all-events.logs-insights" 6
Invoke-BoundedQuery "errors" "$PSScriptRoot/../queries/errors.logs-insights" 2
Write-Host "Both bounded Logs Insights queries returned exact counts for runtime namespace $Namespace and Pod $podName; decoded results and scan statistics were saved locally."
