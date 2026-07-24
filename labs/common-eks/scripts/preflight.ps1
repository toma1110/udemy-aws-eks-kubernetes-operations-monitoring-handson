. "$PSScriptRoot/common.ps1"
$account = Assert-Preflight
Assert-ExactCidr $env:API_PUBLIC_ACCESS_CIDR
$deadline = Get-DeadlineContract
$azs = Assert-SelectedAzsAndCapacity
$quota = Assert-EksQuotaHeadroom

$template = (Resolve-Path "$PSScriptRoot/../template.yaml").Path
$guardTemplate = (Resolve-Path "$PSScriptRoot/../cleanup-guard.yaml").Path
$null = Get-AwsJson -Arguments @(
    "cloudformation", "validate-template", "--region", $Region,
    "--template-body", "file://$template"
)
$null = Get-AwsJson -Arguments @(
    "cloudformation", "validate-template", "--region", $Region,
    "--template-body", "file://$guardTemplate"
)

$existing = Invoke-AwsAllowExactNotFound `
    -Arguments @("cloudformation", "describe-stacks", "--region", $Region, "--stack-name", $StackName) `
    -NotFoundPattern "ValidationError.*does not exist"
if ($existing.Found) {
    throw "The fixed stack already exists. Creation is rejected; use status/delete after ownership binding."
}
$existingGuard = Invoke-AwsAllowExactNotFound `
    -Arguments @("cloudformation", "describe-stacks", "--region", $Region, "--stack-name", $GuardStackName) `
    -NotFoundPattern "ValidationError.*does not exist"
if ($existingGuard.Found) {
    throw "The fixed cleanup guard stack already exists. Creation is rejected; use delete after exact binding."
}

Write-Host "Preflight passed for both absent fixed stacks, exact account input, $Region, AZs $($azs.A)/$($azs.B), quota $($quota.Used)/$($quota.Limit), and deadline $($deadline.Utc)."
