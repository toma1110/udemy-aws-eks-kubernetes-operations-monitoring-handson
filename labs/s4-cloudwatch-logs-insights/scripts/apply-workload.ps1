. "$PSScriptRoot/common.ps1"
$null = Assert-ExternalBinding

$namespace = Invoke-NativeResult "kubectl" @("get", "namespace", $Namespace, "-o", "name")
if ($namespace.ExitCode -eq 0) { throw "The fixed namespace already exists." }
if ($namespace.Output -notmatch "NotFound") { throw "Namespace check failed: $($namespace.Output)" }

$null = Invoke-Kubectl @("apply", "-f", "$PSScriptRoot/../manifests/00-namespace.yaml")
$null = Invoke-Kubectl @("apply", "-f", "$PSScriptRoot/../manifests/10-log-workload.yaml")
$null = Invoke-Kubectl @("wait", "--for=condition=complete", "job/$JobName", "-n", $Namespace, "--timeout=5m")
$podName = Get-ExactJobPodName
$logs = Invoke-Kubectl @("logs", $podName, "-n", $Namespace)
$lines = @($logs -split "`r?`n" | Where-Object { $_ })
$null = @(Assert-WorkloadLogRows -Lines $lines -PodName $podName)
Write-Host "Real EKS Job completed; its exact owned Pod $podName emitted six namespace/Pod-validated JSON log lines."
