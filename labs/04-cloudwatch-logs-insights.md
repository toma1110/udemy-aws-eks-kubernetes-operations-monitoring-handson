# 04. CloudWatch LogsとLogs InsightsでPodログを追う

## 目的

CloudWatch LogsとLogs Insightsを使い、namespace、Pod名、時間帯でログを絞り込みます。

## Log group確認

```powershell
aws logs describe-log-groups --region ap-northeast-1 --log-group-name-prefix "/aws/containerinsights/<cluster-name>" --query "logGroups[].logGroupName" --output table
```

## Logs Insightsの最初のクエリ

```text
fields @timestamp, kubernetes.namespace_name, kubernetes.pod_name, log
| sort @timestamp desc
| limit 50
```

エラー文字列で絞る例:

```text
fields @timestamp, kubernetes.namespace_name, kubernetes.pod_name, log
| filter log like /error|Error|ERROR|Exception/
| sort @timestamp desc
| limit 50
```

## 見るポイント

- 対象リージョンが合っているか
- log group名が想定と合っているか
- 時間帯が広すぎないか
- namespaceやPod名で絞れているか
- アプリケーションログと収集コンポーネントのログを混同していないか

## 記録欄

```text
Log group:
検索時間帯:
クエリ:
見つかったエラー:
次に確認する対象:
```
