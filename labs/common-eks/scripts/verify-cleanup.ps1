. "$PSScriptRoot/common.ps1"
$null = Assert-Preflight $false
$failures = [System.Collections.Generic.List[string]]::new()

$stack = Invoke-AwsAllowExactNotFound `
    -Arguments @("cloudformation", "describe-stacks", "--region", $Region, "--stack-name", $StackName) `
    -NotFoundPattern "ValidationError.*does not exist"
if ($stack.Found) { $failures.Add("CloudFormation stack still exists") }

$cluster = Invoke-AwsAllowExactNotFound `
    -Arguments @("eks", "describe-cluster", "--region", $Region, "--name", $ClusterName) `
    -NotFoundPattern "ResourceNotFoundException"
if ($cluster.Found) { $failures.Add("EKS cluster still exists") }

$tagFilters = @(
    "Name=tag:Course,Values=C010",
    "Name=tag:Lab,Values=section-s5",
    "Name=tag:ManagedBy,Values=udemy4",
    "Name=tag:Purpose,Values=training",
    "Name=tag:TemplateContract,Values=$TemplateContract"
)
$instanceJson = Get-AwsJson -Arguments (@(
    "ec2", "describe-instances", "--region", $Region, "--filters"
) + $tagFilters + @("Name=instance-state-name,Values=pending,running,stopping,stopped,shutting-down"))
if (@($instanceJson.Reservations | ForEach-Object { $_.Instances } | Where-Object { $_ }).Count) {
    $failures.Add("Tagged EC2 instances remain")
}
$volumeJson = Get-AwsJson -Arguments (@("ec2", "describe-volumes", "--region", $Region, "--filters") + $tagFilters)
if (@($volumeJson.Volumes).Count) { $failures.Add("Tagged EBS volumes remain") }
$eniJson = Get-AwsJson -Arguments (@("ec2", "describe-network-interfaces", "--region", $Region, "--filters") + $tagFilters)
if (@($eniJson.NetworkInterfaces).Count) { $failures.Add("Tagged ENIs remain") }
$clusterEniJson = Get-AwsJson -Arguments @(
    "ec2", "describe-network-interfaces", "--region", $Region,
    "--filters", "Name=description,Values=Amazon EKS $ClusterName"
)
if (@($clusterEniJson.NetworkInterfaces).Count) { $failures.Add("EKS-described ENIs remain") }
$logJson = Get-AwsJson -Arguments @(
    "logs", "describe-log-groups", "--region", $Region,
    "--log-group-name-prefix", "/aws/eks/$ClusterName/"
)
if (@($logJson.logGroups).Count) { $failures.Add("Cluster-prefixed CloudWatch log groups remain") }

if ($failures.Count -gt 0) {
    throw "Cleanup verification failed closed: $($failures -join '; ')"
}

# The external guard remains active until all chargeable-residual checks above
# succeed. Bind its exact target before removing only that guard stack.
$guard = Get-ExpectedGuardBinding
$schedule = Get-AwsJson -Arguments @(
    "scheduler", "get-schedule", "--region", $Region,
    "--name", $guard.ScheduleName
)
if ($schedule.Name -cne $GuardScheduleName -or
    $schedule.State -cne "ENABLED" -or
    $schedule.Target.RoleArn -cne "arn:aws:iam::$($guard.Account):role/$GuardRoleName" -or
    $schedule.Target.Arn -cne "arn:aws:scheduler:::aws-sdk:cloudformation:deleteStack" -or
    $schedule.Target.Input -cne '{"StackName":"udemy4-c010-common-20260724"}') {
    throw "Cleanup guard schedule binding mismatch."
}

$null = Invoke-Aws -Arguments @(
    "cloudformation", "delete-stack", "--region", $Region,
    "--stack-name", $guard.StackId
)
$null = Invoke-Aws -Arguments @(
    "cloudformation", "wait", "stack-delete-complete", "--region", $Region,
    "--stack-name", $guard.StackId
)

$guardAfter = Invoke-AwsAllowExactNotFound `
    -Arguments @("cloudformation", "describe-stacks", "--region", $Region, "--stack-name", $GuardStackName) `
    -NotFoundPattern "ValidationError.*does not exist"
if ($guardAfter.Found) { throw "Cleanup guard stack still exists." }
$scheduleAfter = Invoke-AwsAllowExactNotFound `
    -Arguments @("scheduler", "get-schedule", "--region", $Region, "--name", $GuardScheduleName) `
    -NotFoundPattern "ResourceNotFoundException"
if ($scheduleAfter.Found) { throw "Cleanup guard schedule still exists." }
$roleAfter = Invoke-AwsAllowExactNotFound `
    -Arguments @("iam", "get-role", "--region", $Region, "--role-name", $GuardRoleName) `
    -NotFoundPattern "NoSuchEntity"
if ($roleAfter.Found) { throw "Cleanup guard role still exists." }

Write-Host "Cleanup verified: every exact chargeable-residual query succeeded before the exact external guard was removed."
