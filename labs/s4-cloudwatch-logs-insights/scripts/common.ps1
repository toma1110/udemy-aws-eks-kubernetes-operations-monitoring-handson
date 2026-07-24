$script:Region = "ap-northeast-1"
$script:ClusterName = "udemy4-c010-common-20260724"
$script:Namespace = "udemy4-s4-logs"
$script:JobName = "s4-log-generator"
$script:LogGroupName = "/udemy4/c010/s4/20260725"
$script:LogStreamName = "sample-workload"
$script:RequiredTags = @{
    Course = "C010"
    Section = "s4"
    ManagedBy = "udemy4"
    Purpose = "training"
}

function Invoke-NativeResult {
    param([string]$FilePath, [string[]]$Arguments)
    $output = & $FilePath @Arguments 2>&1 | Out-String
    [pscustomobject]@{ ExitCode = $LASTEXITCODE; Output = $output.Trim() }
}

function Invoke-CheckedNative {
    param([string]$FilePath, [string[]]$Arguments)
    $result = Invoke-NativeResult $FilePath $Arguments
    if ($result.ExitCode -ne 0) { throw "$FilePath failed: $($result.Output)" }
    $result.Output
}

function Invoke-Aws {
    param([string[]]$Arguments)
    Invoke-CheckedNative "aws" (@($Arguments) + @("--no-cli-pager"))
}

function Get-AwsJson {
    param([string[]]$Arguments)
    $text = Invoke-Aws (@($Arguments) + @("--output", "json"))
    try { $text | ConvertFrom-Json } catch { throw "AWS CLI returned invalid JSON." }
}

function Invoke-Kubectl {
    param([string[]]$Arguments)
    Invoke-CheckedNative "kubectl" $Arguments
}

function Get-ExactJobPodName {
    $jobText = Invoke-Kubectl @("get", "job", $script:JobName, "-n", $script:Namespace, "-o", "json")
    $podsText = Invoke-Kubectl @("get", "pods", "-n", $script:Namespace, "-l", "job-name=$($script:JobName)", "-o", "json")
    try {
        $job = $jobText | ConvertFrom-Json
        $pods = $podsText | ConvertFrom-Json
    } catch {
        throw "kubectl returned invalid Job or Pod JSON."
    }
    $items = @($pods.items)
    if ($items.Count -ne 1) {
        throw "Expected exactly one Pod selected by the exact Job label; found $($items.Count)."
    }
    $pod = $items[0]
    $owners = @($pod.metadata.ownerReferences | Where-Object {
        $_.kind -ceq "Job" -and
        $_.name -ceq $script:JobName -and
        $_.uid -ceq $job.metadata.uid -and
        $_.controller -eq $true
    })
    if ($owners.Count -ne 1 -or -not $pod.metadata.name) {
        throw "The selected Pod is not owned by the exact runtime Job."
    }
    [string]$pod.metadata.name
}

function Assert-WorkloadLogRows {
    param(
        [Parameter(Mandatory = $true)][string[]]$Lines,
        [Parameter(Mandatory = $true)][string]$PodName
    )
    if ($Lines.Count -ne 6) { throw "Expected exactly six workload JSON rows." }
    foreach ($line in $Lines) {
        try { $event = $line | ConvertFrom-Json } catch { throw "Job emitted non-JSON output." }
        foreach ($field in @("timestamp", "namespace", "pod", "level", "message", "request_id")) {
            if (-not $event.$field) { throw "Job log is missing $field." }
        }
        if ($event.namespace -cne $script:Namespace) {
            throw "Job log namespace does not equal the exact runtime namespace."
        }
        if ($event.pod -cne $PodName) {
            throw "Job log Pod does not equal the exact runtime Job-owned Pod."
        }
        $event
    }
}

function Assert-ExternalBinding {
    if (-not (Get-Command aws -ErrorAction SilentlyContinue)) { throw "AWS CLI v2 is required." }
    if (-not (Get-Command kubectl -ErrorAction SilentlyContinue)) { throw "kubectl is required." }
    $expected = $env:AWS_ACCOUNT_ID
    if (-not $expected -or $expected -notmatch "^\d{12}$") {
        throw "Set AWS_ACCOUNT_ID to the exact approved 12-digit account."
    }
    $identity = Get-AwsJson @("sts", "get-caller-identity", "--region", $script:Region)
    if ($identity.Account -cne $expected) { throw "STS account does not equal AWS_ACCOUNT_ID." }
    $cluster = Get-AwsJson @("eks", "describe-cluster", "--region", $script:Region, "--name", $script:ClusterName)
    $expectedArn = "arn:aws:eks:$($script:Region):$expected`:cluster/$($script:ClusterName)"
    if ($cluster.cluster.arn -cne $expectedArn -or $cluster.cluster.status -cne "ACTIVE") {
        throw "Exact common EKS cluster binding is not ACTIVE."
    }
    $context = (Invoke-Kubectl @("config", "current-context")).Trim()
    if ($context -cne $expectedArn) { throw "kubectl context must equal the exact common cluster ARN." }
    $expected
}

function Test-ExactNotFound {
    param([string[]]$Arguments, [string]$Pattern)
    $result = Invoke-NativeResult "aws" (@($Arguments) + @("--region", $script:Region, "--no-cli-pager"))
    if ($result.ExitCode -eq 0) { return $false }
    if ($result.Output -match $Pattern -and $result.Output -notmatch "AccessDenied|Unauthorized|ExpiredToken|InvalidClientToken|Throttl|timed out|Could not connect|network") {
        return $true
    }
    throw "AWS check failed and was not an exact not-found result: $($result.Output)"
}

function Get-EvidenceDirectory {
    $path = $env:EVIDENCE_DIR
    if (-not $path -or -not [IO.Path]::IsPathFullyQualified($path)) {
        throw "Set EVIDENCE_DIR to an absolute local directory outside both Git worktrees."
    }
    $resolved = Resolve-Path -LiteralPath $path -ErrorAction Stop
    if (-not (Get-Item -LiteralPath $resolved).PSIsContainer) { throw "EVIDENCE_DIR must be a directory." }
    $configured = $env:UDEMY4_PUBLIC
    if (-not $configured -or -not [IO.Path]::IsPathFullyQualified($configured)) {
        throw "Set UDEMY4_PUBLIC to the exact absolute public Git worktree path."
    }
    $configuredPath = (Resolve-Path -LiteralPath $configured -ErrorAction Stop).Path
    $gitRoot = Invoke-NativeResult "git" @("-C", $configuredPath, "rev-parse", "--show-toplevel")
    if ($gitRoot.ExitCode -ne 0) { throw "UDEMY4_PUBLIC is not inside a Git worktree." }
    $exactRoot = (Resolve-Path -LiteralPath $gitRoot.Output -ErrorAction Stop).Path
    if ($configuredPath -cne $exactRoot) { throw "UDEMY4_PUBLIC must equal the exact Git worktree root." }
    Assert-EvidenceOutsideWorktrees -EvidencePath $resolved.Path -WorktreeRoots @($exactRoot)

    $evidenceGit = Invoke-NativeResult "git" @("-C", $resolved.Path, "rev-parse", "--show-toplevel")
    if ($evidenceGit.ExitCode -eq 0) {
        throw "EVIDENCE_DIR must not be inside any Git worktree."
    }
    $resolved.Path
}

function Test-PathInsideRoot {
    param(
        [Parameter(Mandatory = $true)][string]$CandidatePath,
        [Parameter(Mandatory = $true)][string]$RootPath
    )
    $candidate = [IO.Path]::GetFullPath($CandidatePath).TrimEnd(
        [IO.Path]::DirectorySeparatorChar,
        [IO.Path]::AltDirectorySeparatorChar
    )
    $root = [IO.Path]::GetFullPath($RootPath).TrimEnd(
        [IO.Path]::DirectorySeparatorChar,
        [IO.Path]::AltDirectorySeparatorChar
    )
    $isWindowsPlatform = [Runtime.InteropServices.RuntimeInformation]::IsOSPlatform(
        [Runtime.InteropServices.OSPlatform]::Windows
    )
    $comparison = if ($isWindowsPlatform) { [StringComparison]::OrdinalIgnoreCase } else { [StringComparison]::Ordinal }
    if ($candidate.Equals($root, $comparison)) { return $true }
    $prefix = $root + [IO.Path]::DirectorySeparatorChar
    $candidate.StartsWith($prefix, $comparison)
}

function Assert-EvidenceOutsideWorktrees {
    param(
        [Parameter(Mandatory = $true)][string]$EvidencePath,
        [Parameter(Mandatory = $true)][string[]]$WorktreeRoots
    )
    foreach ($root in $WorktreeRoots) {
        if (Test-PathInsideRoot -CandidatePath $EvidencePath -RootPath $root) {
            throw "EVIDENCE_DIR must be outside the root and public Git worktrees."
        }
    }
}
