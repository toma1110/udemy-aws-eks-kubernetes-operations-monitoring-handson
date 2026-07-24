. "$PSScriptRoot/../../common-eks/scripts/common.ps1"
$script:Namespace = "udemy4-c010-s5-20260724"

function Assert-S5Target {
    $account = Assert-Preflight
    $null = Get-ExpectedStackBinding
    $null = Assert-ExactKubernetesContext $account
    return $account
}
