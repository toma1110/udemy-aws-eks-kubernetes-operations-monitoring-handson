. "$PSScriptRoot/common.ps1"
$null = Assert-ExternalBinding

$namespace = Invoke-NativeResult "kubectl" @("get", "namespace", $Namespace, "-o", "json")
if ($namespace.ExitCode -eq 0) {
    try { $namespaceObject = $namespace.Output | ConvertFrom-Json } catch {
        throw "Namespace lookup returned invalid JSON."
    }
    if ($namespaceObject.metadata.name -cne $Namespace) {
        throw "Namespace identity mismatch."
    }
    $expectedNamespaceLabels = @{
        course = "c010"
        section = "s4"
        "managed-by" = "udemy4"
    }
    foreach ($key in $expectedNamespaceLabels.Keys) {
        $actual = $namespaceObject.metadata.labels.$key
        if ($actual -cne $expectedNamespaceLabels[$key]) {
            throw "Namespace ownership label mismatch: $key."
        }
    }

    $job = Invoke-NativeResult "kubectl" @("get", "job", $JobName, "-n", $Namespace, "-o", "json")
    if ($job.ExitCode -eq 0) {
        try { $jobObject = $job.Output | ConvertFrom-Json } catch {
            throw "Job lookup returned invalid JSON."
        }
        if ($jobObject.metadata.name -cne $JobName -or $jobObject.metadata.namespace -cne $Namespace) {
            throw "Job identity mismatch."
        }
        foreach ($key in $expectedNamespaceLabels.Keys) {
            $actual = $jobObject.metadata.labels.$key
            if ($actual -cne $expectedNamespaceLabels[$key]) {
                throw "Job ownership label mismatch: $key."
            }
        }
    } elseif ($job.Output -notmatch "NotFound") {
        throw "Job ownership lookup failed: $($job.Output)"
    }
    $null = Invoke-Kubectl @("delete", "namespace", $Namespace, "--wait=true", "--timeout=5m")
} elseif ($namespace.Output -notmatch "NotFound") {
    throw "Namespace lookup failed: $($namespace.Output)"
}

$groups = Get-AwsJson @("logs", "describe-log-groups", "--region", $Region, "--log-group-name-prefix", $LogGroupName)
$exact = @($groups.logGroups | Where-Object { $_.logGroupName -ceq $LogGroupName })
if ($exact.Count -gt 1) { throw "Exact log group lookup was not unique." }
if ($exact.Count -eq 1) {
    $tags = Get-AwsJson @("logs", "list-tags-log-group", "--region", $Region, "--log-group-name", $LogGroupName)
    foreach ($key in $RequiredTags.Keys) {
        if ($tags.tags.$key -cne $RequiredTags[$key]) { throw "Log group ownership tag mismatch: $key." }
    }
    $null = Invoke-Aws @("logs", "delete-log-group", "--region", $Region, "--log-group-name", $LogGroupName)
}
& "$PSScriptRoot/verify-cleanup.ps1"
if (-not $?) { throw "Section cleanup verification failed." }
