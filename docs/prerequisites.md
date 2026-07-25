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

一般の演習や既存resource向けscriptは、EKSクラスターを自動作成しません。新規作成する場合は、[Amazon EKS クラスターの作成](https://docs.aws.amazon.com/eks/latest/userguide/create-cluster.html)を確認し、作成するVPC、サブネット、IAMロール、ノード、実行時間、削除方法を先に決めてください。

限定された共通EKS routeとして、Section 4とSection 5はAWS Management Consoleで東京`ap-northeast-1`を選んで起動するAWS CloudShellのBashを既定環境とし、[共通EKS基盤](../labs/common-eks/README.md)の`scripts/create.sh`で固定名の短命な学習用stackとEKSクラスターを作成します。AWS CLI `2.12.3`以上、cluster versionと同じか前後1 minor以内の`kubectl`、`jq`、Python 3、事前認証済みconsole identity、Region別`$HOME`の空き容量を確認します。scriptはREADMEに記載したexact account、Region、CIDR、期限、固定名を検証し、既存stackの更新や引き継ぎを行いません。Section 4またはSection 5のREADMEに沿う共通基盤以外で、既存クラスターや任意resourceを作成するgeneral-purpose scriptとして使用しないでください。

## Container Insightsの前提

OTel Container Insightsを有効にするには、既存のEKSクラスター、AWS CLI、`kubectl`接続、EKS Pod IdentityまたはIRSA、CloudWatchへ送信する権限が必要です。設定後、メトリクスやログがCloudWatchに出るまで数分かかります。
