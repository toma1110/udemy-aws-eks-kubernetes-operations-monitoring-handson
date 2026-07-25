# コスト確認と削除確認

## 残りやすいリソース

学習後は、EKSクラスターだけでなく周辺リソースも確認します。

- EKSクラスター
- Managed node group
- Fargate profile
- EC2インスタンス
- Load Balancer
- EBSボリューム
- Security group
- NAT Gateway
- CloudWatch log group
- CloudWatch alarm
- IAM role
- Pod Identity association
- CloudFormation stack

## 読み取り専用の確認

```powershell
aws eks list-clusters --region ap-northeast-1 --output table
aws logs describe-log-groups --region ap-northeast-1 --log-group-name-prefix "/aws/containerinsights" --query "logGroups[].logGroupName" --output table
aws cloudformation list-stacks --region ap-northeast-1 --stack-status-filter CREATE_COMPLETE UPDATE_COMPLETE UPDATE_ROLLBACK_COMPLETE IMPORT_COMPLETE --query "StackSummaries[].[StackName,StackStatus]" --output table
```

## Kubernetes側の削除前確認

EKSクラスターを削除する前に、Kubernetes側で外部リソースを持つServiceやIngressを確認します。

```powershell
kubectl get svc --all-namespaces
kubectl get ingress --all-namespaces
```

`EXTERNAL-IP`を持つServiceやIngressがある場合、Load Balancerが残る可能性があります。削除対象を確認してから、対象のServiceやIngressを削除します。

## EKS側の削除確認

AWS公式ドキュメントでは、クラスター削除前にService、Ingress、node group、Fargate profile、self-managed node用CloudFormation stackなどを確認する流れが示されています。

一般の演習や既存resourceに対する一括削除scriptは、誤削除を避けるため提供しません。自分が作成したresource名を確認してから、AWS公式ドキュメントの手順に沿って削除してください。

限定された共通EKS routeとして、Section 4とSection 5は[共通EKS基盤](../labs/common-eks/README.md)の`scripts/delete.sh`を使います。先に実行したSection固有のcleanupを完了し、Section 4では`labs/s4-cloudwatch-logs-insights/scripts/cleanup-section.sh`でexact namespaceとlog group、Section 5では`labs/s5-pod-resource-first-response/scripts/cleanup-section.sh`でexact namespaceの不存在を確認します。その後にcommon `scripts/delete.sh`を実行すると、s4とs5両方の残存gate、作成時と同じexact account、Region、固定stack/cluster、ownership tagを再照合して、共通の短命な学習用stackだけを削除します。残存確認が完了するまで外部cleanup guardを保持し、既存クラスター、任意resource、Section固有cleanupを通っていないresourceを一括削除しません。

## 削除後の確認

```powershell
aws eks list-clusters --region ap-northeast-1 --output table
aws logs describe-log-groups --region ap-northeast-1 --log-group-name-prefix "/aws/containerinsights" --query "logGroups[].logGroupName" --output table
```

CloudWatch Logsは学習記録として残す場合があります。残すか削除するかは、チームや個人のポリシーに従って判断してください。
