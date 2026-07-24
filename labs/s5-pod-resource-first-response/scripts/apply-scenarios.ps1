. "$PSScriptRoot/common.ps1"
$null = Assert-S5Target

$null = Invoke-Kubectl -Arguments @("apply", "-f", "$PSScriptRoot/../manifests/00-namespace.yaml")
$null = Invoke-Kubectl -Arguments @("apply", "-f", "$PSScriptRoot/../manifests/10-pending-capacity.yaml")
$null = Invoke-Kubectl -Arguments @("apply", "-f", "$PSScriptRoot/../manifests/20-crashloop-app.yaml")
$null = Invoke-Kubectl -Arguments @("apply", "-f", "$PSScriptRoot/../manifests/30-crashloop-memory.yaml")
Write-Output (Invoke-Kubectl -Arguments @("get", "pods", "-n", $Namespace, "-o", "wide"))
