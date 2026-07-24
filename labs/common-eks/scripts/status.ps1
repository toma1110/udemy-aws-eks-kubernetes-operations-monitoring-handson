. "$PSScriptRoot/common.ps1"
$account = Assert-Preflight
$binding = Get-ExpectedStackBinding
$null = Assert-ExactKubernetesContext $account

Write-Output (Invoke-Aws -Arguments @("cloudformation", "describe-stacks", "--region", $Region, "--stack-name", $binding.StackId))
Write-Output (Invoke-Aws -Arguments @("eks", "describe-cluster", "--region", $Region, "--name", $ClusterName))
Write-Output (Invoke-Aws -Arguments @("eks", "list-nodegroups", "--region", $Region, "--cluster-name", $ClusterName))
Write-Output (Invoke-Kubectl -Arguments @("get", "nodes", "-o", "wide"))
