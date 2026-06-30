param(
    [string]$Region = "ap-northeast-1"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Test-Command {
    param([string]$Name)

    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($null -eq $command) {
        [pscustomobject]@{ Name = $Name; Available = $false; Detail = "not found" }
        return
    }

    [pscustomobject]@{ Name = $Name; Available = $true; Detail = $command.Source }
}

Write-Host "Tool check"
Test-Command "aws" | Format-Table -AutoSize
Test-Command "kubectl" | Format-Table -AutoSize
Test-Command "eksctl" | Format-Table -AutoSize

Write-Host ""
Write-Host "AWS CLI version"
aws --version

Write-Host ""
Write-Host "Configured region"
aws configure get region

Write-Host ""
Write-Host "EKS clusters in $Region"
aws eks list-clusters --region $Region --query "clusters" --output table

Write-Host ""
Write-Host "kubectl current context"
$previousErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$contextOutput = & kubectl config current-context 2>$null
$contextExitCode = $LASTEXITCODE
$ErrorActionPreference = $previousErrorActionPreference
if ($contextExitCode -eq 0 -and -not [string]::IsNullOrWhiteSpace($contextOutput)) {
    Write-Host $contextOutput
}
else {
    Write-Host "kubectl context is not set."
}
