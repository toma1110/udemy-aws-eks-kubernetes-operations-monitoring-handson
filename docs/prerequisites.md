# 事前準備

## 必要なツール

- PowerShell
- AWS CLI v2
- `kubectl`
- AWS Management Consoleへログインできるブラウザ

任意:

- `eksctl`
- Docker Desktop
- ローカルKubernetes環境

## AWS側の前提

EKSクラスターを新しく作る場合は、AWS公式ドキュメントで次の前提を確認します。

- EKS要件を満たすVPCと2つ以上のサブネット
- EKSクラスター用IAMロール
- クラスター作成、参照、kubeconfig更新に必要な権限
- Container Insightsを使う場合は、EKS Pod IdentityまたはIRSA、CloudWatchへ送信するIAM権限
- CloudWatchエンドポイントへHTTPSで到達できるネットワーク

## PC側の確認

```powershell
.\scripts\verify_prereqs.ps1
```

このスクリプトはツールの有無、AWS CLIのリージョン、EKSクラスター一覧の取得可否を確認します。`kubectl`の現在のcontextに前後が数字でない12桁の数字列が含まれる場合、その数字列を`[REDACTED_AWS_ACCOUNT_ID]`に置き換えて表示します。認証情報の値を表示する処理はありません。

`collect_readonly_evidence.ps1`も、保存する`kubectl_context`へ同じ置換を適用します。この置換の対象は`kubectl`のcontextだけです。クラスター名やロググループ名など、ほかのAWS出力にIDが含まれないことを保証するものではないため、生成した`artifacts/readonly_evidence.json`は共有前に確認してください。

## クラスターがない場合

このリポジトリだけではEKSクラスターを自動作成しません。新規作成する場合は、[Amazon EKS クラスターの作成](https://docs.aws.amazon.com/eks/latest/userguide/create-cluster.html)を確認し、作成するVPC、サブネット、IAMロール、ノード、実行時間、削除方法を先に決めてください。

## Container Insightsの前提

OTel Container Insightsを有効にするには、既存のEKSクラスター、AWS CLI、`kubectl`接続、EKS Pod IdentityまたはIRSA、CloudWatchへ送信する権限が必要です。設定後、メトリクスやログがCloudWatchに出るまで数分かかります。
