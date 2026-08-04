# AWS EKS Kubernetes監視・運用ハンズオン

このリポジトリは、Amazon EKSでPod、Node、ログ、メトリクス、イベント、権限まわりを初動確認するための受講者向けハンズオンです。

## 使い方

```bash
git clone https://github.com/toma1110/udemy-aws-eks-kubernetes-operations-monitoring-handson.git
cd udemy-aws-eks-kubernetes-operations-monitoring-handson
```

1. Section 2は、[共通EKS上でKubernetes監視の基礎を確認する](labs/s2-kubernetes-baseline/README.md)から始めます。既定環境は東京RegionのAWS CloudShell Bashです。AWSを使わない補助練習として、[固定データで行うKubernetes初動診断](labs/s2-kubernetes-initial-triage/README.md)も残しています。
2. AWS環境を使う演習では、先に[前提条件](docs/prerequisites.md)と[コスト・クリーンアップ](docs/cost-and-cleanup.md)を確認します。
3. 既存のlocal PowerShell教材を使うSectionでは、[PC側の前提条件確認](scripts/verify_prereqs.ps1)を実行します。
4. Section 4は、[EKS PodログをCloudWatch Logs / Logs Insightsで追う](labs/s4-cloudwatch-logs-insights/README.md)を入口にします。既定環境はAWS Management Consoleで東京`ap-northeast-1`を選んで起動するAWS CloudShellのBashです。local PowerShellは不要です。AWS CLI `2.12.3`以上、`kubectl`、`jq`、Python 3、preauthenticated console identity、Region別`$HOME` 1 GBの空きを確認します。同じcheckoutのcommon EKSを使い、Section scriptがnamespace `udemy4-s4-logs`、Job `s4-log-generator`、log group `/udemy4/c010/s4/20260725`、log stream `sample-workload`を作成し、Section cleanup scriptがそれらを削除・残存確認してからcommon cleanupを行います。
5. Section 5は、[Pending / CrashLoopBackOffの初動切り分け](labs/s5-pod-resource-first-response/README.md)を入口にします。repository rootから`cd labs/s5-pod-resource-first-response`を実行し、そのREADMEに従って共通EKS基盤とSection scenarioを順に進めます。作成を許可された自分のAWSアカウントだけを使用し、約USD 0.97/6時間の基礎概算と変動要因を確認してから始めます。
6. Section 6は、[ServiceAccount・RBAC・IAMの関係を観察する](labs/s6-permissions-first-response/README.md)を入口にします。東京RegionのAWS CloudShell Bashから共通EKS基盤を読み取り、権限を追加せずにKubernetesとAWSの判定層を分けて確認します。
7. Section 7は、[メトリクスやログが見えないときの初動切り分け](labs/s7-observability-first-response/README.md)を入口にします。東京RegionのAWS CloudShell Bashから共通EKS基盤を読み取り専用で観察し、add-on、Agent、設定、IAM、network、Region、時間範囲を分けて確認します。
8. Section 8は、[初動対応Runbookとコスト・削除確認](labs/s8-operations-runbook/README.md)を入口にします。東京RegionのAWS CloudShell Bashから共通EKS基盤を読み取り専用で観察し、Runbook、料金発生源、所有権、cleanup順序を確認します。
9. 許可された既存EKSクラスターを読むだけの場合は、[読み取り専用の状態確認](scripts/collect_readonly_evidence.ps1)を利用できます。既存リソースを教材の削除対象にしません。

## 演習一覧

| 講義 | 演習 | ファイル |
| --- | --- | --- |
| s2-l3 | 共通EKS上のbaseline workloadを`kubectl get`で確認する | [labs/s2-kubernetes-baseline/README.md](labs/s2-kubernetes-baseline/README.md) |
| s2-l4 | 実Podを`describe`、`logs`、eventsで深掘りする | [labs/s2-kubernetes-baseline/README.md](labs/s2-kubernetes-baseline/README.md) |
| s3-l4 | Container Insightsと`kubectl`を同じPod・Node・時間帯で照合する | [labs/s3-container-insights/README.md](labs/s3-container-insights/README.md) |
| s4-l2 / s4-l3 | 実EKS JobログをCloudWatch Logsへ送り、Logs Insightsで絞る。AWSを使えない場合はfixtureで回帰確認する | [labs/s4-cloudwatch-logs-insights/README.md](labs/s4-cloudwatch-logs-insights/README.md) |
| s5-l3 / s5-l4 | 短命なEKS基盤でPendingとCrashLoopBackOffを調べる | [labs/s5-pod-resource-first-response/README.md](labs/s5-pod-resource-first-response/README.md) |
| s6-l4 / s6-l5 | ServiceAccount、RBAC、AWS権限の関係を読み取り専用で確認する | [labs/s6-permissions-first-response/README.md](labs/s6-permissions-first-response/README.md) |
| s7-l2 / s7-l3 | メトリクスやログが見えないときを切り分ける | [labs/s7-observability-first-response/README.md](labs/s7-observability-first-response/README.md) |
| s8-l3 / s8-l4 | 初動対応Runbookを作り、コストと安全な削除順序を確認する | [labs/s8-operations-runbook/README.md](labs/s8-operations-runbook/README.md) |

## AWS利用時の注意

EKS、EC2、NAT Gateway、CloudWatch Logs、Container Insights、Load Balancerなどは料金が発生する場合があります。演習前に必ず次を決めてください。

- 利用するAWSアカウントとリージョン
- 使うEKSクラスター名
- 作成してよいリソース
- 学習を終える時刻
- 削除対象にしてよいリソース
- 残してよいログと残してはいけないログ

`labs/common-eks/scripts/create.sh`、Section 4の`apply-workload.sh` / `publish-logs.sh` / `cleanup-section.sh`、Section 5のscenario/cleanup scriptは、明示された固定名の学習用リソースを作成・削除します。Section 4ではnamespace、Job、CloudWatch Logs log group、log streamが対象です。ほかの既存クラスター向け確認scriptとfixture routeは読み取り専用です。固定stackまたは固定Section resourceが既に存在する場合は更新や引き継ぎをせず停止します。

Section 5のlive routeは、AWS Management Consoleで東京`ap-northeast-1`を選んで起動するAWS CloudShellのBash、AWS CLI `2.12.3`以上、cluster versionと同じか前後1 minor以内の`kubectl`、`jq`、Python 3、事前認証済みconsole identityを前提にします。local PowerShellは不要です。Pod imageは`busybox:1.36.1`と`python:3.12-alpine`へtag固定されています。EKS control plane versionはtemplateで固定せず、実行時に利用可能な標準サポート版が選ばれるため、作成直前にAWS公式情報と`kubectl`互換性を再確認してください。

## 公式ドキュメント

- [Amazon EKS クラスターの作成](https://docs.aws.amazon.com/eks/latest/userguide/create-cluster.html)
- [Amazon EKS クラスターの削除](https://docs.aws.amazon.com/eks/latest/userguide/delete-cluster.html)
- [OTel Container Insights on Amazon EKS](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/container-insights-eks-otel-quickstart.html)
- [CloudWatch Observability EKS add-on](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/install-CloudWatch-Observability-EKS-addon.html)

## ライセンス

このリポジトリは MIT License で提供します。条件は [LICENSE](LICENSE) を確認してください。
