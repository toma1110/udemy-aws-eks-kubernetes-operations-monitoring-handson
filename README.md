# AWS EKS Kubernetes監視・運用ハンズオン

このリポジトリは、Amazon EKSでPod、Node、ログ、メトリクス、イベント、権限まわりを初動確認するための受講者向けハンズオンです。

## 使い方

1. [docs/prerequisites.md](docs/prerequisites.md)で必要なツールとAWSの利用境界を確認します。
2. [scripts/verify_prereqs.ps1](scripts/verify_prereqs.ps1)でPC側の準備状況を確認します。
3. 既存のEKSクラスターがある場合は、[scripts/collect_readonly_evidence.ps1](scripts/collect_readonly_evidence.ps1)で読み取り専用の状態確認を行います。
4. 講義に合わせて[labs](labs)配下の演習を進めます。
5. 学習後は[docs/cost-and-cleanup.md](docs/cost-and-cleanup.md)で残りリソースを確認します。

## 演習一覧

| 講義 | 演習 | ファイル |
| --- | --- | --- |
| s2-l3 | `kubectl get`で全体を見る | [labs/01-kubectl-first-look.md](labs/01-kubectl-first-look.md) |
| s2-l4 | `describe`、`logs`、eventsで深掘りする | [labs/02-describe-logs-events.md](labs/02-describe-logs-events.md) |
| s3-l4 | Container Insightsの画面を読む | [labs/03-container-insights.md](labs/03-container-insights.md) |
| s4-l2 / s4-l3 | CloudWatch LogsとLogs InsightsでPodログを追う | [labs/04-cloudwatch-logs-insights.md](labs/04-cloudwatch-logs-insights.md) |
| s5-l3 / s5-l4 | PendingとCrashLoopBackOffの初動対応 | [labs/05-pod-failure-first-response.md](labs/05-pod-failure-first-response.md) |
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

このリポジトリのスクリプトは、既定では読み取り専用の確認に寄せています。削除や作成は、各自の環境で対象を確認してから実行してください。

## 公式ドキュメント

- [Amazon EKS クラスターの作成](https://docs.aws.amazon.com/eks/latest/userguide/create-cluster.html)
- [Amazon EKS クラスターの削除](https://docs.aws.amazon.com/eks/latest/userguide/delete-cluster.html)
- [OTel Container Insights on Amazon EKS](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/container-insights-eks-otel-quickstart.html)
- [CloudWatch Observability EKS add-on](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/install-CloudWatch-Observability-EKS-addon.html)

## ライセンス

ライセンスは未設定です。再配布や商用利用は、公開時に設定されるライセンスを確認してください。
