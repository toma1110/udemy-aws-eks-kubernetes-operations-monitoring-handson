param(
    [string]$Region = "ap-northeast-1",
    [string]$ClusterName = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Write-Host "This script lists possible remaining resources. It does not delete anything."
Write-Host ""

Write-Host "EKS clusters"
aws eks list-clusters --region $Region --output table

Write-Host ""
Write-Host "Container Insights log groups"
aws logs describe-log-groups `
    --region $Region `
    --log-group-name-prefix "/aws/containerinsights" `
    --query "logGroups[].logGroupName" `
    --output table

Write-Host ""
Write-Host "CloudFormation stacks"
aws cloudformation list-stacks `
    --region $Region `
    --stack-status-filter CREATE_COMPLETE UPDATE_COMPLETE UPDATE_ROLLBACK_COMPLETE IMPORT_COMPLETE `
    --query "StackSummaries[].[StackName,StackStatus]" `
    --output table

if (-not [string]::IsNullOrWhiteSpace($ClusterName)) {
    Write-Host ""
    Write-Host "Node groups for $ClusterName"
    aws eks list-nodegroups --region $Region --cluster-name $ClusterName --output table

    Write-Host ""
    Write-Host "Fargate profiles for $ClusterName"
    aws eks list-fargate-profiles --region $Region --cluster-name $ClusterName --output table
}

Write-Host ""
Write-Host "Before deleting an EKS cluster, also check Kubernetes Service and Ingress resources."
