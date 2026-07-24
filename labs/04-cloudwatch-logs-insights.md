# 04. CloudWatch LogsとLogs InsightsでPodログを追う

## 目的

CloudWatch LogsとLogs Insightsを使い、namespace、Pod名、時間帯でログを絞り込みます。

## Section 4演習

[EKS PodログをCloudWatch Logs / Logs Insightsで追う](s4-cloudwatch-logs-insights/README.md)では、同じrepositoryのcommon EKSへSection固有Jobを追加し、実ログをfixed log groupへ送り、15分以内のqueryで読みます。AWSを使えない場合は同じREADMEのfixture fallbackを使います。

以下の一般例ではなく、resource名、account binding、cleanupが固定されたSection 4 READMEを実行手順の正本にしてください。

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

## コストとcleanup

Logs Insightsはスキャン量に応じて料金が発生し得ます。実環境では短い時間帯と必要なlog groupに限定し、実行時にAWS公式料金を確認してください。Section 4演習はJob、namespace、log group、log streamを作成するため、Section 4 READMEのcleanupと残存確認が必須です。
