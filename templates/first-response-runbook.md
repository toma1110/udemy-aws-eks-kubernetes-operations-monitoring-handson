# 初動対応Runbook

## 1. 症状

```text
何が起きているか:
いつから:
影響を受ける利用者:
影響を受けるnamespace:
```

## 2. まず見る場所

```powershell
kubectl get pods -A -o wide
kubectl get nodes
kubectl get events -A --sort-by=.lastTimestamp
```

## 3. Pod確認

```text
対象Pod:
STATUS:
RESTARTS:
NODE:
直近ログ:
```

## 4. Node確認

```text
対象Node:
Ready状態:
CPU:
memory:
taint:
```

## 5. ログ確認

```text
CloudWatch log group:
Logs Insights query:
見つかったエラー:
```

## 6. メトリクス確認

```text
CPU:
memory:
restart:
network:
確認した時間帯:
```

## 7. 権限確認

```text
ServiceAccount:
RBAC:
AWS側の関連付け:
AccessDeniedの有無:
```

## 8. 次の判断

```text
暫定原因:
追加確認:
エスカレーション条件:
学んだこと:
```
