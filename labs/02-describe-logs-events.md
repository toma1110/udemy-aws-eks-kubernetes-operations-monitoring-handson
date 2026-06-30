# 02. `describe`、`logs`、eventsで深掘りする

## 目的

一覧で気になったPodを深掘りし、ログ、イベント、終了理由から初動仮説を作ります。

## コマンド

```powershell
kubectl describe pod <pod-name> -n <namespace>
kubectl logs <pod-name> -n <namespace> --tail=100
kubectl get events -n <namespace> --sort-by=.lastTimestamp
```

直前に落ちたコンテナを見る場合:

```powershell
kubectl logs <pod-name> -n <namespace> --previous --tail=100
```

## 見るポイント

- container stateとlast state
- restart reason
- image pullエラー
- probe failure
- scheduling failure
- application error

## 記録欄

```text
Pod:
namespace:
describeで見えた異常:
logsで見えた異常:
eventsで見えた異常:
次に確認すること:
```
