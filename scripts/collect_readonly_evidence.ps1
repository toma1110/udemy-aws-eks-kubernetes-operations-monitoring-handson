param(
    [string]$Region = "ap-northeast-1",
    [string]$ClusterName = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Protect-KubectlContext {
    param([string]$Value)

    [regex]::Replace($Value, '(?<!\d)\d{12}(?!\d)', '[REDACTED_AWS_ACCOUNT_ID]')
}

$artifactDir = Join-Path (Get-Location) "artifacts"
New-Item -ItemType Directory -Path $artifactDir -Force | Out-Null

$result = [ordered]@{
    created_at = (Get-Date).ToString("s")
    region = $Region
    aws_cli = (aws --version)
    eks_clusters = $null
    container_insights_log_groups = $null
    kubectl_context = $null
    cluster = $null
}

$result.eks_clusters = aws eks list-clusters --region $Region --query "clusters" --output json | ConvertFrom-Json
$result.container_insights_log_groups = aws logs describe-log-groups `
    --region $Region `
    --log-group-name-prefix "/aws/containerinsights" `
    --query "logGroups[].logGroupName" `
    --output json | ConvertFrom-Json

$previousErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$contextOutput = & kubectl config current-context 2>$null
$contextExitCode = $LASTEXITCODE
$ErrorActionPreference = $previousErrorActionPreference
if ($contextExitCode -eq 0 -and -not [string]::IsNullOrWhiteSpace($contextOutput)) {
    $result.kubectl_context = Protect-KubectlContext -Value ($contextOutput -join [Environment]::NewLine)
}
else {
    $result.kubectl_context = "not set"
}

if (-not [string]::IsNullOrWhiteSpace($ClusterName)) {
    $result.cluster = [ordered]@{
        name = $ClusterName
        status = (aws eks describe-cluster --region $Region --name $ClusterName --query "cluster.status" --output text)
        addon_status = $null
    }

    try {
        $result.cluster.addon_status = aws eks describe-addon `
            --region $Region `
            --cluster-name $ClusterName `
            --addon-name amazon-cloudwatch-observability `
            --query "addon.status" `
            --output text
    }
    catch {
        $result.cluster.addon_status = "not found or not accessible"
    }
}

$outPath = Join-Path $artifactDir "readonly_evidence.json"
$result | ConvertTo-Json -Depth 8 | Set-Content -Path $outPath -Encoding utf8
Write-Host "Saved $outPath"
