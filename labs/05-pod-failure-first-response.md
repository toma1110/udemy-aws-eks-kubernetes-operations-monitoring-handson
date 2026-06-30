# 05. PendingとCrashLoopBackOffの初動対応

## Pendingを見る

```powershell
kubectl get pod <pod-name> -n <namespace> -o wide
kubectl describe pod <pod-name> -n <namespace>
kubectl get nodes
kubectl describe node <node-name>
```

確認観点:

- insufficient cpu
- insufficient memory
- taintとtoleration
- node selector
- affinity
- volume mount
- image pull

## CrashLoopBackOffを見る

```powershell
kubectl describe pod <pod-name> -n <namespace>
kubectl logs <pod-name> -n <namespace> --previous --tail=100
kubectl get events -n <namespace> --sort-by=.lastTimestamp
```

確認観点:

- exit code
- OOMKilled
- probe failure
- missing environment variable
- application error

## 記録欄

```text
症状:
対象Pod:
namespace:
Node:
イベント:
ログ:
初動仮説:
```
