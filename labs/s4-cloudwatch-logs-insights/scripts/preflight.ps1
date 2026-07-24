. "$PSScriptRoot/common.ps1"
$null = Assert-ExternalBinding

$namespace = Invoke-NativeResult "kubectl" @("get", "namespace", $Namespace, "-o", "name")
if ($namespace.ExitCode -eq 0) { throw "The fixed namespace already exists; do not adopt or update it." }
if ($namespace.Output -notmatch "NotFound") { throw "Namespace preflight failed: $($namespace.Output)" }

$logGroupAbsent = Test-ExactNotFound `
    @("logs", "describe-log-groups", "--log-group-name-prefix", $LogGroupName, "--output", "json") `
    "never-match"
if ($logGroupAbsent) { throw "Unexpected describe-log-groups not-found behavior." }
$groups = Get-AwsJson @("logs", "describe-log-groups", "--region", $Region, "--log-group-name-prefix", $LogGroupName)
if (@($groups.logGroups | Where-Object { $_.logGroupName -ceq $LogGroupName }).Count -ne 0) {
    throw "The fixed log group already exists; do not adopt or update it."
}
Write-Host "Section 4 preflight passed for exact account, Region, cluster context, and absent fixed resources."
