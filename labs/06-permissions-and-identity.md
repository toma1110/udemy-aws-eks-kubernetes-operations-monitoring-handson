# 06. ServiceAccount、RBAC、AWS権限を確認する

## 目的

Podが使うServiceAccountと、Kubernetes側・AWS側の権限の入口を確認します。

## Kubernetes側

```powershell
kubectl get serviceaccount -n <namespace>
kubectl describe serviceaccount <serviceaccount-name> -n <namespace>
kubectl get rolebinding,clusterrolebinding -A
kubectl describe rolebinding <rolebinding-name> -n <namespace>
```

## ServiceAccountのYAML

```powershell
kubectl get serviceaccount <serviceaccount-name> -n <namespace> -o yaml
```

## CloudWatch Observability add-onまわり

```powershell
aws eks describe-addon --cluster-name <cluster-name> --addon-name amazon-cloudwatch-observability
kubectl get pods -n amazon-cloudwatch
kubectl get pods -n amazon-cloudwatch
kubectl logs <cloudwatch-pod-name> -n amazon-cloudwatch --tail=100
```

## 見るポイント

- PodがどのServiceAccountを使っているか
- ServiceAccountにAWS側の関連付けがあるか
- RoleBindingやClusterRoleBindingが期待通りか
- `AccessDenied`がアプリケーション起因か、監視Pod起因か
- CloudWatchへ送信する権限があるか

## 記録欄

```text
対象Pod:
ServiceAccount:
RoleBinding:
AWS側の関連付け:
AccessDeniedの場所:
次に見るログ:
```
