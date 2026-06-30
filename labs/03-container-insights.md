# 03. Container Insightsの画面を読む

## 目的

CloudWatch Container Insightsで、Pod、Node、namespace、workloadの状態を確認します。

## 事前確認

- EKSクラスターが存在する
- `kubectl`が対象クラスターへ接続できる
- CloudWatch Observability add-onまたはCloudWatch収集コンポーネントが設定済み
- CloudWatchへメトリクスとログを送信できるIAM権限がある
- 設定後、数分待っている

## 確認コマンド

```powershell
aws eks describe-addon --cluster-name <cluster-name> --addon-name amazon-cloudwatch-observability --query "addon.status" --output text
kubectl get pods -n amazon-cloudwatch
kubectl get pods -n amazon-cloudwatch
```

## 画面で見る場所

CloudWatch ConsoleでContainer Insightsを開き、次を確認します。

- Cluster view
- Nodes
- Pods
- Namespaces
- Workloads

## 見るポイント

- CPUやmemoryが高いPod
- restartが多いPod
- Nodeごとの偏り
- namespaceごとの負荷
- メトリクスが表示されるまでの待ち時間

## 記録欄

```text
クラスター名:
確認した画面:
CPUが高い対象:
memoryが高い対象:
restartが目立つ対象:
気づき:
```
