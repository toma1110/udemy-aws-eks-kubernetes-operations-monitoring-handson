. "$PSScriptRoot/common.ps1"
$null = Assert-Preflight $false
$stack = Invoke-AwsAllowExactNotFound `
    -Arguments @("cloudformation", "describe-stacks", "--region", $Region, "--stack-name", $StackName) `
    -NotFoundPattern "ValidationError.*does not exist"
if ($stack.Found) {
    $binding = Get-ExpectedStackBinding
    $null = Invoke-Aws -Arguments @(
        "cloudformation", "delete-stack", "--region", $Region,
        "--stack-name", $binding.StackId
    )
    $null = Invoke-Aws -Arguments @(
        "cloudformation", "wait", "stack-delete-complete", "--region", $Region,
        "--stack-name", $binding.StackId
    )
}
& "$PSScriptRoot/verify-cleanup.ps1"
if (-not $?) { throw "Cleanup verification script failed." }
