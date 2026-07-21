# Kubernetes 初動診断：固定データで `get` から深掘りまで

この演習では、Kubernetes の固定済み疑似出力を使って、一覧から異常候補を選び、`describe`、`logs`、events をつないで初動仮説を立てます。クラスタや AWS アカウントには接続しません。

## 目的

- Node、namespace、Pod の一覧から調査対象を選べる
- Pod 名と namespace をそろえて `describe`、`logs`、events を照合できる
- Pending、CrashLoopBackOff、OOMKilled で最初の確認先を分けられる
- 1つの出力だけで原因を断定せず、根拠と次の確認を説明できる

## 前提条件とバージョン

- Python 3.11 以上（標準ライブラリだけを使用）
- PowerShell、コマンドプロンプト、または一般的なシェル
- `kubectl`、AWS CLI、AWS アカウント、Kubernetes クラスタは不要

教材の JSON は Kubernetes API の代表的な項目を学習用に単純化した合成データです。実環境の完全な API 応答ではありません。

### 実環境コマンドと固定データの対応

次の `kubectl` コマンドは参照用であり、この演習では**実行しません**。クラスタ接続とcredentialを前提にせず、右欄の固定データを `Get-Content` で読むことで同じ確認順序を練習します。

| 実環境で対応するコマンド（未実行） | この演習で読む固定データ |
| --- | --- |
| `kubectl get nodes` | `fixtures/get-nodes.json` |
| `kubectl get namespaces` | `fixtures/get-namespaces.json` |
| `kubectl get pods -n training` | `fixtures/get-pods.json` |
| `kubectl describe pod pending-api -n training` | `fixtures/describe-pending-api.json` |
| `kubectl describe pod crashloop-worker -n training` | `fixtures/describe-crashloop-worker.json` |
| `kubectl describe pod oom-reporter -n training` | `fixtures/describe-oom-reporter.json` |
| `kubectl logs crashloop-worker -n training` | `fixtures/logs-crashloop-worker-current.txt` |
| `kubectl logs crashloop-worker -n training --previous` | `fixtures/logs-crashloop-worker-previous.txt` |
| `kubectl logs oom-reporter -n training --previous` | `fixtures/logs-oom-reporter-previous.txt` |
| `kubectl get events -n training --sort-by=.lastTimestamp` | `fixtures/events.json` |

実環境で試す場合は、別途正しいcluster context、対象namespace、参照権限が必要です。この教材の完了条件には含めず、AWSアカウント、クラスタ、credentialは用意しないでください。

## 手順

1. リポジトリをcloneし、この演習ディレクトリへ移動します。

   ```powershell
   git clone https://github.com/toma1110/udemy-aws-eks-kubernetes-operations-monitoring-handson.git
   cd udemy-aws-eks-kubernetes-operations-monitoring-handson/labs/s2-kubernetes-initial-triage
   ```

2. Node の一覧を確認します。

   ```powershell
   Get-Content fixtures/get-nodes.json
   ```

   期待結果: 2台の Node があり、どちらも `Ready` です。Node 全体の停止より先に、個別 Pod を調べる判断ができます。

3. namespace と Pod の一覧を確認します。

   ```powershell
   Get-Content fixtures/get-namespaces.json
   Get-Content fixtures/get-pods.json
   ```

   期待結果: `training` namespace に `pending-api`、`crashloop-worker`、`oom-reporter` という3つの異常候補が見つかります。`healthy-web` は `Running`、再起動0回です。

4. Pending の情報を同じ対象で照合します。

   ```powershell
   Get-Content fixtures/describe-pending-api.json
   Get-Content fixtures/events.json
   ```

   期待結果: `pending-api` は未配置で、同じ Pod の `FailedScheduling` event に `Insufficient memory` が記録されています。初動仮説は「要求メモリに対して配置可能な Node 容量が不足」です。

5. CrashLoopBackOff の情報を照合します。

   ```powershell
   Get-Content fixtures/describe-crashloop-worker.json
   Get-Content fixtures/logs-crashloop-worker-current.txt
   Get-Content fixtures/logs-crashloop-worker-previous.txt
   Get-Content fixtures/events.json
   ```

   期待結果: 現在ログだけでなく、前回ログの `required setting APP_MODE is missing` と同じ Pod の `BackOff` event を確認できます。初動仮説は「必須設定の欠落で起動後に終了」です。

6. OOMKilled の情報を照合します。

   ```powershell
   Get-Content fixtures/describe-oom-reporter.json
   Get-Content fixtures/logs-oom-reporter-previous.txt
   ```

   期待結果: Pod の現在状態は `Running` でも、再起動回数が3回で、前回終了理由は `OOMKilled` です。初動仮説は「コンテナがメモリ上限へ到達」です。

7. すべての固定データを検証し、診断結果を作ります。

   ```powershell
   python analyze.py --check
   ```

   期待結果: `PASS: fixtures and analysis match expected-results.json` と表示され、終了コードは0です。

8. テストを実行します。

   ```powershell
   python -m unittest discover -s tests -v
   ```

   期待結果: すべてのテストが `ok` になり、最後に `OK` と表示されます。

## 診断の読み方

生成される診断は原因確定ではありません。`get` は異常候補を絞る入口、`describe` は現在状態と前回状態、`logs` はコンテナ内部の記録、events は周辺で起きた変化を示します。同じ namespace と Pod を指す事実だけを組み合わせます。

## トラブルシューティング

| 症状 | 確認すること |
| --- | --- |
| `python` が見つからない | Python 3.11 以上をインストールし、`python --version` を確認する |
| `FileNotFoundError` | この README があるディレクトリでコマンドを実行する |
| JSON の解析エラー | `fixtures/` のファイルを変更していないか確認し、元の教材へ戻す |
| `expected-results.json` と不一致 | 固定データ、分析コード、期待結果のいずれかが変更されているため、3点を同じ版にそろえる |
| PowerShell 以外を使用 | `Get-Content` の代わりに、利用中の環境の安全なテキスト表示コマンドを使う |

## コスト

この演習の費用は **0円** です。ローカルファイルを読むだけで、AWS API や Kubernetes クラスタへ接続しません。AWS リソースを作成、更新、削除するコマンドは含みません。

## クリーンアップ

クラウドリソースは作成されないため、クラウド側の削除は不要です。ローカルの出力をファイルへ保存した場合だけ、その不要な出力ファイルを通常のファイル操作で削除してください。`fixtures/`、`expected-results.json`、`analyze.py` は演習の入力なので削除しません。

## ファイル

- `fixtures/`: 固定済みの合成 `get`、`describe`、`logs`、events 出力
- `expected-results.json`: 正しい診断結果
- `analyze.py`: 標準ライブラリだけで動く検証・診断コード
- `tests/`: 決定的な単体テスト
