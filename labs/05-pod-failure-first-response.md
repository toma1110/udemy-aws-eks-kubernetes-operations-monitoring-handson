# 05. PendingとCrashLoopBackOffの初動対応

実習本体は[Pod リソース問題の初動切り分け](s5-pod-resource-first-response/README.md)です。Primary route では、許可された既存 EKS クラスターの context、namespace、Pod を固定し、`kubectl`、EKS Console、Container Insightsを読み取り専用で照合します。問題状態の Pod、参照権限、またはメトリクスがない場合も異常とは断定せず、「live結果なし」と記録して固定済み合成データの fallback route へ進みます。

fallback route は Python 3.11 以上と PowerShell だけで再現でき、AWS アカウントや Kubernetes クラスターは不要です。どちらのrouteも新しいクラウドリソースを作成、更新、再起動、scale、削除しません。既存 EKS、Node、CloudWatch、Container Insightsには既存料金が発生している場合があります。

以下は、live routeで同じ対象を確認するときの読み取り専用メモです。`<context>`、`<namespace>`、`<pod>`、`<node>`を許可された対象へ置き換え、対象を固定できない場合は実行せずfallback routeへ進んでください。ここに示す出力は例ではなく確認コマンドだけであり、PendingやCrashLoopBackOffが実環境に存在するとは主張しません。

## Pendingを見る

```powershell
kubectl --context <context> get pod <pod> -n <namespace> -o wide
kubectl --context <context> describe pod <pod> -n <namespace>
kubectl --context <context> get events -n <namespace> --field-selector involvedObject.kind=Pod,involvedObject.name=<pod> --sort-by=.lastTimestamp
kubectl --context <context> get nodes -o wide
kubectl --context <context> describe node <node>
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
kubectl --context <context> describe pod <pod> -n <namespace>
kubectl --context <context> logs <pod> -n <namespace> --tail=100
kubectl --context <context> logs <pod> -n <namespace> --previous --tail=100
kubectl --context <context> get events -n <namespace> --field-selector involvedObject.kind=Pod,involvedObject.name=<pod> --sort-by=.lastTimestamp
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
次の読み取り確認:
```

観察できた事実だけを記録します。別 Pod のeventやログを代用せず、状態名だけで原因を確定しません。具体的な手順、fixtureの期待結果、コスト、クリーンアップ、安全境界は実習本体のREADMEを参照してください。
