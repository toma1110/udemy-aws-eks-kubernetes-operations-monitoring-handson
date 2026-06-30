# 01. `kubectl get`で全体を見る

## 目的

クラスターに接続した直後に、Node、namespace、Podの状態を一覧で確認します。

## コマンド

```powershell
kubectl get nodes
kubectl get namespaces
kubectl get pods --all-namespaces
kubectl get pods -A -o wide
```

## 見るポイント

- Nodeが`Ready`か
- `Running`以外のPodがあるか
- restart回数が増えているPodがあるか
- 特定のNodeにPodが偏っていないか
- `kube-system`や`amazon-cloudwatch`のPodが期待通り動いているか

## 記録欄

```text
確認日時:
クラスター名:
気になったnamespace:
気になったPod:
最初の仮説:
```
