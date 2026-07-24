. "$PSScriptRoot/common.ps1"
$null = Assert-S5Target

$null = Invoke-Kubectl -Arguments @("get", "namespace", $Namespace)
$null = Invoke-Kubectl -Arguments @("delete", "namespace", $Namespace, "--wait=true", "--timeout=5m")
$result = Invoke-NativeResult -FilePath "kubectl" -Arguments @("get", "namespace", $Namespace)
if ($result.ExitCode -eq 0) {
    throw "Section namespace still exists. Do not continue to common cleanup."
}
if ($result.Output -notmatch "NotFound") {
    throw "Namespace verification failed and was not an exact NotFound result: $($result.Output)"
}
Write-Host "Section namespace cleanup verified."
