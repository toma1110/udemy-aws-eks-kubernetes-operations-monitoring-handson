# 04. CloudWatch LogsとLogs InsightsでPodログを追う

## 目的

CloudWatch LogsとLogs Insightsを使い、namespace、Pod名、時間帯でログを絞り込みます。

## 最初に行うオフライン演習

[固定合成ログを使う演習](s4-cloudwatch-logs-insights/README.md)では、AWSアカウントやEKSクラスターなしで、namespace、Pod名、時間帯、エラーを絞り、時系列で読む手順を再現できます。Python 3.11以上の標準ライブラリだけを使い、費用は0円です。

以下は、承認済みの既存AWS環境で同じ観点を確認する場合の参考です。AWS CLI実行はオフライン演習の完了条件ではありません。

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

Logs Insightsはスキャン量に応じて料金が発生し得ます。実環境では短い時間帯と必要なlog groupに限定し、実行時にAWS公式料金を確認してください。この手順は読み取りだけでリソースを作成しないため、通常はAWS側のcleanupはありません。
