. "$PSScriptRoot/common.ps1"
$null = Assert-ExternalBinding
$evidence = Get-EvidenceDirectory

$groups = Get-AwsJson @("logs", "describe-log-groups", "--region", $Region, "--log-group-name-prefix", $LogGroupName)
if (@($groups.logGroups | Where-Object { $_.logGroupName -ceq $LogGroupName }).Count -ne 0) {
    throw "The fixed log group already exists; this script never adopts or updates it."
}

$podName = Get-ExactJobPodName
$raw = Invoke-Kubectl @("logs", $podName, "-n", $Namespace)
$lines = @($raw -split "`r?`n" | Where-Object { $_ })
$validatedRows = @(Assert-WorkloadLogRows -Lines $lines -PodName $podName)
$events = for ($index = 0; $index -lt $lines.Count; $index++) {
    $item = $validatedRows[$index]
    $at = [DateTimeOffset]::Parse($item.timestamp)
    [ordered]@{ timestamp = $at.ToUnixTimeMilliseconds(); message = $lines[$index] }
}
$eventsPath = Join-Path $evidence "put-log-events.json"
$events | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $eventsPath -Encoding utf8NoBOM

$null = Invoke-Aws @("logs", "create-log-group", "--region", $Region, "--log-group-name", $LogGroupName)
$tagArgs = @()
foreach ($key in ($RequiredTags.Keys | Sort-Object)) { $tagArgs += "$key=$($RequiredTags[$key])" }
$null = Invoke-Aws (@("logs", "tag-log-group", "--region", $Region, "--log-group-name", $LogGroupName, "--tags") + $tagArgs)
$null = Invoke-Aws @("logs", "put-retention-policy", "--region", $Region, "--log-group-name", $LogGroupName, "--retention-in-days", "1")
$null = Invoke-Aws @("logs", "create-log-stream", "--region", $Region, "--log-group-name", $LogGroupName, "--log-stream-name", $LogStreamName)
$putResponseText = Invoke-Aws @("logs", "put-log-events", "--region", $Region, "--log-group-name", $LogGroupName, "--log-stream-name", $LogStreamName, "--log-events", "file://$eventsPath", "--output", "json")
try { $putResponse = $putResponseText | ConvertFrom-Json } catch {
    throw "PutLogEvents returned invalid JSON."
}
if (
    $putResponse.PSObject.Properties.Name -contains "rejectedLogEventsInfo" -and
    $null -ne $putResponse.rejectedLogEventsInfo
) {
    throw "PutLogEvents rejected one or more events: $($putResponse.rejectedLogEventsInfo | ConvertTo-Json -Compress)"
}
$putResponse | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $evidence "put-log-events-response.json") -Encoding utf8NoBOM

$readback = $null
for ($attempt = 0; $attempt -lt 15; $attempt++) {
    $readback = Get-AwsJson @(
        "logs", "get-log-events", "--region", $Region,
        "--log-group-name", $LogGroupName,
        "--log-stream-name", $LogStreamName,
        "--start-from-head"
    )
    if (@($readback.events).Count -eq 6) { break }
    Start-Sleep -Seconds 1
}
if (@($readback.events).Count -ne 6) {
    throw "CloudWatch readback did not return exactly six events."
}
$expectedMessages = @($lines | Sort-Object)
$actualMessages = @($readback.events | ForEach-Object { $_.message } | Sort-Object)
if (Compare-Object $expectedMessages $actualMessages) {
    throw "CloudWatch readback messages differ from the six Job log lines."
}
$readback | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $evidence "get-log-events-readback.json") -Encoding utf8NoBOM

$times = $events | ForEach-Object { [DateTimeOffset]::FromUnixTimeMilliseconds($_.timestamp) }
$start = (($times | Measure-Object -Minimum).Minimum).AddMinutes(-2).ToUnixTimeSeconds()
$end = (($times | Measure-Object -Maximum).Maximum).AddMinutes(2).ToUnixTimeSeconds()
if (($end - $start) -gt 900) { throw "Generated query range exceeds 15 minutes." }
[ordered]@{
    schema = "udemy4-s4-query-window-v1"
    region = $Region
    log_group = $LogGroupName
    start_epoch = $start
    end_epoch = $end
    max_range_seconds = 900
} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $evidence "query-window.json") -Encoding utf8NoBOM
Write-Host "PutLogEvents reported no rejected events and readback matched all six Job log lines; the bounded query window was saved locally."
