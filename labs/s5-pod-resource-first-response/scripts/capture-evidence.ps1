. "$PSScriptRoot/common.ps1"
$null = Assert-S5Target

$evidence = Join-Path $env:TEMP "udemy4-c010-s5-20260724-evidence"
New-Item -ItemType Directory -Path $evidence -Force | Out-Null

Invoke-Kubectl -Arguments @("get", "pods", "-n", $Namespace, "-o", "yaml") | Out-File "$evidence/pods.yaml" -Encoding utf8
Invoke-Kubectl -Arguments @("get", "events", "-n", $Namespace, "--sort-by=.lastTimestamp") | Out-File "$evidence/events.txt" -Encoding utf8
Invoke-Kubectl -Arguments @("describe", "pod", "udemy4-c010-s5-20260724-pending-capacity", "-n", $Namespace) | Out-File "$evidence/pending-capacity-describe.txt" -Encoding utf8
Invoke-Kubectl -Arguments @("describe", "pod", "udemy4-c010-s5-20260724-crashloop-app", "-n", $Namespace) | Out-File "$evidence/crashloop-app-describe.txt" -Encoding utf8
Invoke-Kubectl -Arguments @("logs", "udemy4-c010-s5-20260724-crashloop-app", "-n", $Namespace, "--tail=100") | Out-File "$evidence/crashloop-app-current.log" -Encoding utf8
Invoke-Kubectl -Arguments @("logs", "udemy4-c010-s5-20260724-crashloop-app", "-n", $Namespace, "--previous", "--tail=100") | Out-File "$evidence/crashloop-app-previous.log" -Encoding utf8
Invoke-Kubectl -Arguments @("describe", "pod", "udemy4-c010-s5-20260724-crashloop-memory", "-n", $Namespace) | Out-File "$evidence/crashloop-memory-describe.txt" -Encoding utf8
Invoke-Kubectl -Arguments @("logs", "udemy4-c010-s5-20260724-crashloop-memory", "-n", $Namespace, "--previous", "--tail=100") | Out-File "$evidence/crashloop-memory-previous.log" -Encoding utf8
Invoke-Kubectl -Arguments @("get", "nodes", "-o", "custom-columns=NAME:.metadata.name,ALLOCATABLE_MEMORY:.status.allocatable.memory") | Out-File "$evidence/node-memory.txt" -Encoding utf8
Write-Host "Evidence captured at $evidence. Review before sharing; do not add it to Git."
