# 07. メトリクスやログが見えないときを切り分ける

## メトリクスが見えない

```powershell
kubectl get pods -n amazon-cloudwatch
kubectl logs <cloudwatch-pod-name> -n amazon-cloudwatch --tail=50
kubectl get daemonset -n amazon-cloudwatch
kubectl get serviceaccount -n amazon-cloudwatch -o yaml
aws eks describe-addon --cluster-name <cluster-name> --addon-name amazon-cloudwatch-observability
```

確認観点:

- CloudWatch収集コンポーネントのPodが`Running`か
- DaemonSetが各Nodeへ配置されているか
- Pod Identity add-onまたはIRSAが使える状態か
- CloudWatch送信権限があるか
- VPCからCloudWatch endpointへ到達できるか

## ログが見えない

```powershell
aws logs describe-log-groups --region ap-northeast-1 --log-group-name-prefix "/aws/containerinsights/<cluster-name>" --query "logGroups[].logGroupName" --output table
kubectl logs <cloudwatch-pod-name> -n amazon-cloudwatch --tail=100
```

確認観点:

- リージョンが合っているか
- log groupが作成されているか
- log groupはあるが空ではないか
- CloudWatch収集設定にログ収集が含まれているか
- 権限エラーやネットワークエラーが出ていないか

## 記録欄

```text
症状:
Cluster:
CloudWatch収集Pod状態:
Add-on状態:
CloudWatch log group:
疑わしい原因:
次の確認:
```
