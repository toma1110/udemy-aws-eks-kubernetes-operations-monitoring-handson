# AWS EKS Kubernetes監視・運用ハンズオン

このリポジトリは、Amazon EKSでPod、Node、ログ、メトリクス、イベント、権限まわりを初動確認するための受講者向けハンズオンです。

## 使い方

```powershell
git clone https://github.com/toma1110/udemy-aws-eks-kubernetes-operations-monitoring-handson.git
cd udemy-aws-eks-kubernetes-operations-monitoring-handson
```

1. Section 2は、[固定データで行うKubernetes初動診断](labs/s2-kubernetes-initial-triage/README.md)から始めます。GitとPython 3.11以上があれば実行でき、AWSアカウントやクラスターは不要、追加のクラウド費用はありません。
2. AWS環境を使う演習では、先に[前提条件](docs/prerequisites.md)と[コスト・クリーンアップ](docs/cost-and-cleanup.md)を確認します。
3. [PC側の前提条件確認](scripts/verify_prereqs.ps1)を実行します。
4. Section 5は、[Pending / CrashLoopBackOffの初動切り分け](labs/s5-pod-resource-first-response/README.md)を入口にします。repository rootから`cd labs/s5-pod-resource-first-response`を実行し、そのREADMEに従って共通EKS基盤とSection scenarioを順に進めます。作成を許可された自分のAWSアカウントだけを使用し、約USD 0.97/6時間の基礎概算と変動要因を確認してから始めます。
5. AWSを使えない場合は、Section 5の同じREADMEにあるfixture routeを実行します。Python 3.11以上だけで決定的に再現でき、AWSアカウントやクラスターは不要です。
6. 許可された既存EKSクラスターを読むだけの場合は、[読み取り専用の状態確認](scripts/collect_readonly_evidence.ps1)を利用できます。既存リソースを教材の削除対象にしません。

## 演習一覧

| 講義 | 演習 | ファイル |
| --- | --- | --- |
| s2-l3 | `kubectl get`に対応する固定データで全体を見る | [labs/s2-kubernetes-initial-triage/README.md](labs/s2-kubernetes-initial-triage/README.md) |
| s2-l4 | `describe`、`logs`、eventsに対応する固定データで深掘りする | [labs/s2-kubernetes-initial-triage/README.md](labs/s2-kubernetes-initial-triage/README.md) |
| s3-l4 | Container Insightsの画面を読む | [labs/03-container-insights.md](labs/03-container-insights.md) |
| s4-l2 / s4-l3 | 固定合成ログでCloudWatch Logs / Logs Insightsの絞り込みを練習する | [labs/s4-cloudwatch-logs-insights/README.md](labs/s4-cloudwatch-logs-insights/README.md) |
| s5-l3 / s5-l4 | 短命なEKS基盤でPendingとCrashLoopBackOffを調べ、AWSを使えない場合は固定データで同じ初動観点を練習する | [labs/s5-pod-resource-first-response/README.md](labs/s5-pod-resource-first-response/README.md) |
| s6-l4 / s6-l5 | ServiceAccount、RBAC、AWS権限を確認する | [labs/06-permissions-and-identity.md](labs/06-permissions-and-identity.md) |
| s7-l2 / s7-l3 | メトリクスやログが見えないときを切り分ける | [labs/07-observability-troubleshooting.md](labs/07-observability-troubleshooting.md) |
| s8-l3 | 初動対応Runbookを作る | [templates/first-response-runbook.md](templates/first-response-runbook.md) |
| s8-l4 | コスト確認と削除確認 | [docs/cost-and-cleanup.md](docs/cost-and-cleanup.md) |

## AWS利用時の注意

EKS、EC2、NAT Gateway、CloudWatch Logs、Container Insights、Load Balancerなどは料金が発生する場合があります。演習前に必ず次を決めてください。

- 利用するAWSアカウントとリージョン
- 使うEKSクラスター名
- 作成してよいリソース
- 学習を終える時刻
- 削除対象にしてよいリソース
- 残してよいログと残してはいけないログ

`labs/common-eks/scripts/create.ps1`とSection 5のscenario/cleanup scriptは、明示された固定名の学習用リソースを作成・削除します。ほかの既存クラスター向け確認scriptとfixture routeは読み取り専用です。固定stackが既に存在する場合は更新や引き継ぎをせず停止します。

Section 5のlive routeはPowerShell 7、AWS CLI v2、`kubectl`、承認済みAWS認証を前提にします。Pod imageは`busybox:1.36.1`と`python:3.12-alpine`へtag固定されています。EKS control plane versionはtemplateで固定せず、実行時に利用可能な標準サポート版が選ばれるため、作成直前にAWS公式情報と`kubectl`互換性を再確認してください。

## 公式ドキュメント

- [Amazon EKS クラスターの作成](https://docs.aws.amazon.com/eks/latest/userguide/create-cluster.html)
- [Amazon EKS クラスターの削除](https://docs.aws.amazon.com/eks/latest/userguide/delete-cluster.html)
- [OTel Container Insights on Amazon EKS](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/container-insights-eks-otel-quickstart.html)
- [CloudWatch Observability EKS add-on](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/install-CloudWatch-Observability-EKS-addon.html)

## ライセンス

このリポジトリは MIT License で提供します。条件は [LICENSE](LICENSE) を確認してください。
