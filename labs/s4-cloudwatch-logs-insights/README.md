# 固定ログで始める CloudWatch Logs / Logs Insights 調査

この演習では、CloudWatch Logsへ届いたPodログを模した固定済み合成JSON Linesを使います。namespace、Pod名、時間帯で対象を探し、エラーだけを時系列に並べる初動調査をローカルで再現します。

**AWSへの接続・実行は行いません。** AWSアカウント、credential、AWS CLI、EKSクラスタは不要です。教材データは実環境から取得したものではありません。

## 目的

- namespace、Pod名、時間帯を組み合わせて対象ログを絞る
- エラーだけを抽出し、複数Podの記録を時系列で読む
- 選択した時間帯が両端を含むことと、別namespace・別Podが除外されることを確認する
- 合成結果を原因確定ではなく初動仮説の材料として扱う

## 前提条件

- Git
- Python 3.11以上（標準ライブラリのみ）
- PowerShell、コマンドプロンプト、または一般的なシェル

## CloudWatchとの対応

`fixtures/cloudwatch-logs.jsonl` の `timestamp`、`namespace`、`pod`、`level`、`message` は、Logs Insightsで選択・表示する代表的な学習用フィールドです。実環境のログフィールド名は収集設定やログ形式で異なるため、実際には対象ログの1件を開いてフィールドを確認してからクエリを合わせます。この演習はAWSコンソールやLogs Insights APIを呼び出しません。

参考となるLogs Insightsの考え方は、時間範囲を画面で指定したうえで、概念的には次のように絞ることです（**未実行の例**）。

```text
fields @timestamp, kubernetes.namespace_name, kubernetes.pod_name, level, @message
| filter kubernetes.namespace_name = "training"
| filter kubernetes.pod_name = "checkout-7d9f"
| sort @timestamp asc
```

実環境では、正しいRegion、log group、時間範囲、参照権限を確認してください。スキャン量に応じたLogs Insights料金が発生し得るため、短い時間範囲と必要なlog groupから始めます。

## 手順

1. repositoryを取得し、このディレクトリへ移動します。

   ```powershell
   git clone https://github.com/toma1110/udemy-aws-eks-kubernetes-operations-monitoring-handson.git
   cd udemy-aws-eks-kubernetes-operations-monitoring-handson/labs/s4-cloudwatch-logs-insights
   ```

2. 合成ログのフィールドを確認します。

   PowerShell:

   ```powershell
   Get-Content fixtures/cloudwatch-logs.jsonl
   ```

   コマンドプロンプト:

   ```bat
   type fixtures\cloudwatch-logs.jsonl
   ```

   POSIX互換シェル:

   ```sh
   cat fixtures/cloudwatch-logs.jsonl
   ```

   期待結果: 10件のJSONレコードがあり、`training`と`payments`、2つのcheckout Pod、時間範囲内外のログが混在しています。

3. `training` namespaceの`checkout-7d9f`を、10:00:00Zから10:06:00Zまでで絞ります。

   ```powershell
   python analyze.py --namespace training --pod checkout-7d9f --start 2026-07-24T10:00:00Z --end 2026-07-24T10:06:00Z
   ```

   期待結果: `count` は5です。10:00と10:06の両端を含み、別Pod、別namespace、09:59、10:07の記録は含みません。

4. 同じ時間帯・namespaceでエラーだけを時系列表示します。

   ```powershell
   python analyze.py --namespace training --start 2026-07-24T10:00:00Z --end 2026-07-24T10:06:00Z --errors
   ```

   期待結果: `count` は3です。10:02の`checkout-7d9f`、10:03の`checkout-8a2c`、10:04の`checkout-7d9f`の順です。`payments`のエラーは除外されます。

5. 期待結果との完全一致を検証します。

   ```powershell
   python analyze.py --check
   ```

   期待結果: `PASS: fixture filters match expected-results.json`、終了コード0。

6. 単体テストを実行します。

   ```powershell
   python -m unittest discover -s tests -v
   ```

   期待結果: 8テストが成功し、最後に`OK`。

## 結果の読み方

`req-101`では遅延、timeout、retry exhaustionが同じPodで続いています。一方、10:03の別Podのエラーは別requestです。時系列の近さだけで同一原因と断定せず、request ID、対象Pod、関連メトリクスや設定を追加確認します。

## トラブルシューティング

| 症状 | 確認 |
| --- | --- |
| `python`が見つからない | `python --version`でPython 3.11以上を確認する |
| `FileNotFoundError` | READMEがある`s4-cloudwatch-logs-insights`ディレクトリで実行する |
| `fixture hash mismatch` | fixtureが変更されています。repositoryの正しい版へ戻す |
| `timestamp must include a timezone` | `Z`または`+09:00`などtimezone付きISO 8601を使う |
| 0件になる | namespace、Pod名、UTCの時間範囲を再確認する |
| 実環境だけ結果が出ない | Region、log group、時間帯、フィールド名、Agentの転送、参照権限を順に確認する |

## コスト

このローカル演習は0円です。AWS APIを呼ばず、AWSリソースを作成・更新・削除しません。実環境でLogs Insightsを使う場合はスキャン量に応じて料金が発生し得ます。この教材では料金額を固定せず、実行時にAWS公式料金を確認し、短い時間帯と必要なlog groupへ限定してください。

## クリーンアップ

クラウドリソースを作らないためAWS側のcleanupは不要です。コマンドは標準出力だけを使い、通常はローカル出力も残りません。自分でリダイレクトして作成した出力ファイルだけを、内容とパスを確認してから削除してください。教材の`fixtures/`、`expected-results.json`、`analyze.py`は削除しません。

## ファイル

- `fixtures/cloudwatch-logs.jsonl`: 固定合成ログ
- `fixtures/manifest.json`: fixtureの改変検出用hash
- `expected-results.json`: 2つの演習の期待結果
- `analyze.py`: ローカルfilter/analyzer
- `tests/test_analyze.py`: 正常系・fail-closedテスト
