. "$PSScriptRoot/common.ps1"
$account = Assert-Preflight
Assert-ExactCidr $env:API_PUBLIC_ACCESS_CIDR
$deadline = Get-DeadlineContract
$azs = Assert-SelectedAzsAndCapacity
$null = Assert-EksQuotaHeadroom

$existing = Invoke-AwsAllowExactNotFound `
    -Arguments @("cloudformation", "describe-stacks", "--region", $Region, "--stack-name", $StackName) `
    -NotFoundPattern "ValidationError.*does not exist"
if ($existing.Found) {
    throw "The fixed stack already exists. This script never updates or adopts it."
}
$existingGuard = Invoke-AwsAllowExactNotFound `
    -Arguments @("cloudformation", "describe-stacks", "--region", $Region, "--stack-name", $GuardStackName) `
    -NotFoundPattern "ValidationError.*does not exist"
if ($existingGuard.Found) {
    throw "The fixed cleanup guard stack already exists. This script never updates or adopts it."
}

$template = (Resolve-Path "$PSScriptRoot/../template.yaml").Path
$guardTemplate = (Resolve-Path "$PSScriptRoot/../cleanup-guard.yaml").Path
$script:guardBinding = $null
Invoke-GuardedCommonCreate `
    -CreateGuard {
        $null = Invoke-Aws -Arguments @(
            "cloudformation", "create-stack",
            "--region", $Region,
            "--stack-name", $GuardStackName,
            "--template-body", "file://$guardTemplate",
            "--capabilities", "CAPABILITY_NAMED_IAM",
            "--parameters",
            "ParameterKey=AccountId,ParameterValue=$account",
            "ParameterKey=CleanupScheduleExpression,ParameterValue=$($deadline.ScheduleExpression)",
            "--tags",
            "Key=Course,Value=C010",
            "Key=Lab,Value=section-s5",
            "Key=ManagedBy,Value=udemy4",
            "Key=Purpose,Value=training-cleanup-guard",
            "Key=TemplateContract,Value=$GuardTemplateContract"
        )
    } `
    -WaitAndBindGuard {
        $null = Invoke-Aws -Arguments @(
            "cloudformation", "wait", "stack-create-complete",
            "--region", $Region, "--stack-name", $GuardStackName
        )
        $script:guardBinding = Get-ExpectedGuardBinding
    } `
    -CreateCommon {
        $null = Invoke-Aws -Arguments @(
            "cloudformation", "deploy",
            "--region", $Region,
            "--stack-name", $StackName,
            "--template-file", $template,
            "--capabilities", "CAPABILITY_IAM",
            "--parameter-overrides",
            "ApiPublicAccessCidr=$($env:API_PUBLIC_ACCESS_CIDR)",
            "AvailabilityZoneA=$($azs.A)",
            "AvailabilityZoneB=$($azs.B)",
            "--tags",
            "Course=C010",
            "Lab=section-s5",
            "ManagedBy=udemy4",
            "Purpose=training",
            "TemplateContract=$TemplateContract"
        )
    }

$binding = Get-ExpectedStackBinding
$null = Invoke-Aws -Arguments @("eks", "update-kubeconfig", "--region", $Region, "--name", $ClusterName)
$null = Assert-ExactKubernetesContext $account
$null = Invoke-Kubectl -Arguments @("wait", "--for=condition=Ready", "nodes", "--all", "--timeout=10m")
Write-Host "Create and ownership binding completed. External guard $($guardBinding.StackId) remains active until verified cleanup; automatic common-stack deletion is scheduled for $($deadline.Utc)."
