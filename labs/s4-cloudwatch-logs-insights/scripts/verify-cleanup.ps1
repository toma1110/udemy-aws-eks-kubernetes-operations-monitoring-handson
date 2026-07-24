. "$PSScriptRoot/common.ps1"
$null = Assert-ExternalBinding
$failures = [System.Collections.Generic.List[string]]::new()

$namespace = Invoke-NativeResult "kubectl" @("get", "namespace", $Namespace, "-o", "name")
if ($namespace.ExitCode -eq 0) { $failures.Add("Section namespace remains") }
elseif ($namespace.Output -notmatch "NotFound") { throw "Namespace residual check failed: $($namespace.Output)" }

$groups = Get-AwsJson @("logs", "describe-log-groups", "--region", $Region, "--log-group-name-prefix", $LogGroupName)
if (@($groups.logGroups | Where-Object { $_.logGroupName -ceq $LogGroupName }).Count -ne 0) {
    $failures.Add("Section log group remains")
}
if ($failures.Count -gt 0) { throw "Cleanup verification failed closed: $($failures -join '; ')" }
Write-Host "Section cleanup verified: namespace, Job, and fixed CloudWatch log group are absent."
