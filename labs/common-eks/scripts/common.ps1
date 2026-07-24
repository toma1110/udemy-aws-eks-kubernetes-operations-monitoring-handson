$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$script:Region = "ap-northeast-1"
$script:StackName = "udemy4-c010-common-20260724"
$script:ClusterName = "udemy4-c010-common-20260724"
$script:TemplateContract = "udemy4-c010-common-eks-v2-20260724"
$script:GuardStackName = "udemy4-c010-common-20260724-guard"
$script:GuardScheduleName = "udemy4-c010-common-20260724-guard-schedule"
$script:GuardRoleName = "udemy4-c010-common-20260724-guard-role"
$script:GuardTemplateContract = "udemy4-c010-cleanup-guard-v1-20260724"
$script:RequiredTags = [ordered]@{
    Course = "C010"
    Lab = "section-s5"
    ManagedBy = "udemy4"
    Purpose = "training"
    TemplateContract = $script:TemplateContract
}
$script:GuardRequiredTags = [ordered]@{
    Course = "C010"
    Lab = "section-s5"
    ManagedBy = "udemy4"
    Purpose = "training-cleanup-guard"
    TemplateContract = $script:GuardTemplateContract
}

function Invoke-NativeResult {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )
    $output = & $FilePath @Arguments 2>&1
    $exitCode = $LASTEXITCODE
    $text = ($output | ForEach-Object { "$_" }) -join "`n"
    return [pscustomobject]@{ ExitCode = $exitCode; Output = $text }
}

function Invoke-CheckedNative {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )
    $result = Invoke-NativeResult -FilePath $FilePath -Arguments $Arguments
    if ($result.ExitCode -ne 0) {
        throw "$FilePath failed with exit $($result.ExitCode): $($result.Output)"
    }
    return $result.Output
}

function Invoke-Aws {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)
    return Invoke-CheckedNative -FilePath "aws" -Arguments (@($Arguments) + @("--no-cli-pager"))
}

function Get-AwsJson {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)
    $text = Invoke-Aws -Arguments (@($Arguments) + @("--output", "json"))
    try {
        return $text | ConvertFrom-Json
    } catch {
        throw "AWS CLI returned invalid JSON for '$($Arguments -join ' ')'."
    }
}

function Invoke-AwsAllowExactNotFound {
    param(
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$NotFoundPattern
    )
    $result = Invoke-NativeResult -FilePath "aws" -Arguments (@($Arguments) + @("--no-cli-pager", "--output", "json"))
    if ($result.ExitCode -eq 0) {
        return [pscustomobject]@{ Found = $true; Output = $result.Output }
    }
    if ($result.Output -match $NotFoundPattern -and
        $result.Output -notmatch "AccessDenied|Unauthorized|ExpiredToken|InvalidClientToken|Throttl|timed out|Could not connect|network") {
        return [pscustomobject]@{ Found = $false; Output = $null }
    }
    throw "AWS CLI failed and was not an exact not-found result: $($result.Output)"
}

function Invoke-Kubectl {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)
    return Invoke-CheckedNative -FilePath "kubectl" -Arguments $Arguments
}

function Assert-RequiredAccountInput {
    $expected = $env:AWS_ACCOUNT_ID
    if (-not $expected -or $expected -notmatch "^\d{12}$") {
        throw "Set AWS_ACCOUNT_ID to the exact 12-digit target account for every external script."
    }
    return $expected
}

function Assert-AwsIdentity {
    $expected = Assert-RequiredAccountInput
    $identity = Get-AwsJson -Arguments @("sts", "get-caller-identity", "--region", $script:Region)
    if ($identity.Account -ne $expected) {
        throw "STS account does not equal AWS_ACCOUNT_ID."
    }
    $regions = Get-AwsJson -Arguments @("ec2", "describe-regions", "--region", $script:Region, "--region-names", $script:Region)
    if (@($regions.Regions).Count -ne 1 -or $regions.Regions[0].RegionName -ne $script:Region) {
        throw "The fixed Region ap-northeast-1 could not be verified."
    }
    return $expected
}

function Assert-Preflight([bool]$RequireKubectl = $true) {
    if (-not (Get-Command aws -ErrorAction SilentlyContinue)) {
        throw "AWS CLI v2 is required."
    }
    if ($RequireKubectl -and -not (Get-Command kubectl -ErrorAction SilentlyContinue)) {
        throw "kubectl is required."
    }
    $version = Invoke-CheckedNative -FilePath "aws" -Arguments @("--version")
    if ($version -notmatch "^aws-cli/2\.") {
        throw "AWS CLI v2 is required; found: $version"
    }
    return Assert-AwsIdentity
}

function Assert-ExactCidr([string]$Cidr) {
    if (-not $Cidr -or $Cidr -eq "0.0.0.0/0" -or $Cidr -notmatch "^(?:\d{1,3}\.){3}\d{1,3}/(?:\d|[12]\d|3[0-2])$") {
        throw "Set API_PUBLIC_ACCESS_CIDR to one exact trusted IPv4 CIDR; 0.0.0.0/0 is rejected."
    }
}

function Get-DeadlineContract {
    $raw = $env:CLEANUP_DEADLINE_UTC
    if (-not $raw -or $raw -notmatch "^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$") {
        throw "Set CLEANUP_DEADLINE_UTC in exact UTC form YYYY-MM-DDTHH:MM:SSZ."
    }
    $deadline = [DateTimeOffset]::ParseExact(
        $raw,
        "yyyy-MM-dd'T'HH:mm:ss'Z'",
        [Globalization.CultureInfo]::InvariantCulture,
        [Globalization.DateTimeStyles]::AssumeUniversal
    )
    $now = [DateTimeOffset]::UtcNow
    if ($deadline -le $now.AddMinutes(15) -or $deadline -gt $now.AddHours(6)) {
        throw "Cleanup deadline must be more than 15 minutes and no more than 6 hours from now."
    }
    return [pscustomobject]@{
        Utc = $raw
        ScheduleExpression = "at($($raw.Substring(0, 19)))"
    }
}

function Assert-SelectedAzsAndCapacity {
    $azA = $env:AVAILABILITY_ZONE_A
    $azB = $env:AVAILABILITY_ZONE_B
    if (-not $azA -or -not $azB -or $azA -eq $azB) {
        throw "Set two distinct AVAILABILITY_ZONE_A and AVAILABILITY_ZONE_B values."
    }
    $zones = Get-AwsJson -Arguments @(
        "ec2", "describe-availability-zones", "--region", $script:Region,
        "--zone-names", $azA, $azB
    )
    $zoneNames = @($zones.AvailabilityZones | Where-Object {
        $_.RegionName -eq $script:Region -and $_.State -eq "available"
    } | ForEach-Object { $_.ZoneName })
    if ($zoneNames.Count -ne 2 -or $azA -notin $zoneNames -or $azB -notin $zoneNames) {
        throw "Both selected AZs must be available in ap-northeast-1."
    }
    foreach ($az in @($azA, $azB)) {
        $offerings = Get-AwsJson -Arguments @(
            "ec2", "describe-instance-type-offerings", "--region", $script:Region,
            "--location-type", "availability-zone",
            "--filters", "Name=location,Values=$az", "Name=instance-type,Values=t3.medium"
        )
        if (@($offerings.InstanceTypeOfferings).Count -lt 1) {
            throw "t3.medium is not offered in selected AZ $az."
        }
    }
    return [pscustomobject]@{ A = $azA; B = $azB }
}

function Assert-EksQuotaHeadroom {
    $quota = Get-AwsJson -Arguments @(
        "service-quotas", "get-service-quota", "--region", $script:Region,
        "--service-code", "eks", "--quota-code", "L-1194D53C"
    )
    $clusters = Get-AwsJson -Arguments @("eks", "list-clusters", "--region", $script:Region)
    $limit = [double]$quota.Quota.Value
    $used = @($clusters.clusters).Count
    if ($limit -lt 1 -or $used -ge $limit) {
        throw "No EKS cluster quota headroom remains ($used used of $limit)."
    }
    return [pscustomobject]@{ Used = $used; Limit = $limit }
}

function Convert-TagsToMap($Tags) {
    $map = @{}
    foreach ($tag in @($Tags)) {
        if ($map.ContainsKey($tag.Key)) {
            throw "Duplicate ownership tag $($tag.Key)."
        }
        $map[$tag.Key] = $tag.Value
    }
    return $map
}

function Assert-ExactTagMap($Tags, [string]$Target) {
    $actual = Convert-TagsToMap $Tags
    if ($actual.Count -ne $script:RequiredTags.Count) {
        throw "$Target has unexpected or missing ownership tags."
    }
    foreach ($key in $script:RequiredTags.Keys) {
        if (-not $actual.ContainsKey($key) -or $actual[$key] -ne $script:RequiredTags[$key]) {
            throw "$Target ownership tag mismatch: $key."
        }
    }
}

function Assert-ExactGuardTagMap($Tags) {
    $actual = Convert-TagsToMap $Tags
    if ($actual.Count -ne $script:GuardRequiredTags.Count) {
        throw "Cleanup guard stack has unexpected or missing ownership tags."
    }
    foreach ($key in $script:GuardRequiredTags.Keys) {
        if (-not $actual.ContainsKey($key) -or $actual[$key] -cne $script:GuardRequiredTags[$key]) {
            throw "Cleanup guard ownership tag mismatch: $key."
        }
    }
}

function Invoke-GuardedCommonCreate {
    param(
        [Parameter(Mandatory = $true)][scriptblock]$CreateGuard,
        [Parameter(Mandatory = $true)][scriptblock]$WaitAndBindGuard,
        [Parameter(Mandatory = $true)][scriptblock]$CreateCommon
    )
    & $CreateGuard
    & $WaitAndBindGuard
    & $CreateCommon
}

function Get-ExpectedGuardBinding {
    $account = Assert-AwsIdentity
    $stacks = Get-AwsJson -Arguments @(
        "cloudformation", "describe-stacks", "--region", $script:Region,
        "--stack-name", $script:GuardStackName
    )
    if (@($stacks.Stacks).Count -ne 1) {
        throw "Expected exactly one fixed cleanup guard stack."
    }
    $stack = $stacks.Stacks[0]
    $expectedStackPrefix = "arn:aws:cloudformation:$($script:Region):$account`:stack/$($script:GuardStackName)/"
    if ($stack.StackName -ne $script:GuardStackName -or
        $stack.StackStatus -cne "CREATE_COMPLETE" -or
        -not $stack.StackId.StartsWith($expectedStackPrefix)) {
        throw "Cleanup guard stack ID, account, Region, or name mismatch."
    }
    Assert-ExactGuardTagMap $stack.Tags
    $outputs = @{}
    foreach ($output in @($stack.Outputs)) {
        if ($outputs.ContainsKey($output.OutputKey)) { throw "Duplicate cleanup guard output." }
        $outputs[$output.OutputKey] = $output.OutputValue
    }
    if ($outputs.Count -ne 5 -or
        $outputs.TargetStackName -cne $script:StackName -or
        $outputs.Region -cne $script:Region -or
        $outputs.TemplateContract -cne $script:GuardTemplateContract -or
        $outputs.ScheduleName -cne $script:GuardScheduleName -or
        $outputs.RoleName -cne $script:GuardRoleName) {
        throw "Cleanup guard output binding mismatch."
    }
    return [pscustomobject]@{
        StackId = $stack.StackId
        Account = $account
        ScheduleName = $script:GuardScheduleName
        RoleName = $script:GuardRoleName
    }
}

function Assert-ExactEksClusterTagMap($Tags, [string]$StackId) {
    $expected = [ordered]@{}
    foreach ($key in $script:RequiredTags.Keys) {
        $expected[$key] = $script:RequiredTags[$key]
    }
    $expected["aws:cloudformation:stack-name"] = $script:StackName
    $expected["aws:cloudformation:stack-id"] = $StackId
    $expected["aws:cloudformation:logical-id"] = "EksCluster"

    $actual = Convert-TagsToMap $Tags
    if ($actual.Count -ne $expected.Count) {
        throw "EKS cluster has unexpected or missing ownership/system tags."
    }
    foreach ($key in $expected.Keys) {
        if (-not $actual.ContainsKey($key) -or $actual[$key] -cne $expected[$key]) {
            throw "EKS cluster ownership/system tag mismatch: $key."
        }
    }
}

function Get-ExpectedStackBinding {
    $account = Assert-AwsIdentity
    $stacks = Get-AwsJson -Arguments @(
        "cloudformation", "describe-stacks", "--region", $script:Region,
        "--stack-name", $script:StackName
    )
    if (@($stacks.Stacks).Count -ne 1) {
        throw "Expected exactly one fixed CloudFormation stack."
    }
    $stack = $stacks.Stacks[0]
    $expectedStackPrefix = "arn:aws:cloudformation:$($script:Region):$account`:stack/$($script:StackName)/"
    if ($stack.StackName -ne $script:StackName -or -not $stack.StackId.StartsWith($expectedStackPrefix)) {
        throw "Stack ID, account, Region, or name mismatch."
    }
    Assert-ExactTagMap $stack.Tags "CloudFormation stack"
    $outputs = @{}
    foreach ($output in @($stack.Outputs)) { $outputs[$output.OutputKey] = $output.OutputValue }
    if ($outputs.ClusterName -ne $script:ClusterName -or
        $outputs.Region -ne $script:Region -or
        $outputs.TemplateContract -ne $script:TemplateContract) {
        throw "Stack output binding mismatch."
    }
    $cluster = Get-AwsJson -Arguments @(
        "eks", "describe-cluster", "--region", $script:Region,
        "--name", $script:ClusterName
    )
    $expectedClusterArn = "arn:aws:eks:$($script:Region):$account`:cluster/$($script:ClusterName)"
    if ($cluster.cluster.name -ne $script:ClusterName -or $cluster.cluster.arn -ne $expectedClusterArn) {
        throw "EKS cluster ARN ownership mismatch."
    }
    $clusterTags = @()
    foreach ($property in $cluster.cluster.tags.PSObject.Properties) {
        $clusterTags += [pscustomobject]@{ Key = $property.Name; Value = "$($property.Value)" }
    }
    Assert-ExactEksClusterTagMap $clusterTags $stack.StackId
    return [pscustomobject]@{
        StackId = $stack.StackId
        ClusterArn = $expectedClusterArn
        Account = $account
    }
}

function Assert-ExactKubernetesContext([string]$Account) {
    $actual = (Invoke-Kubectl -Arguments @("config", "current-context")).Trim()
    $expected = "arn:aws:eks:$($script:Region):$Account`:cluster/$($script:ClusterName)"
    if ($actual -cne $expected) {
        throw "Current kubectl context must equal the exact expected EKS cluster ARN."
    }
    return $expected
}
