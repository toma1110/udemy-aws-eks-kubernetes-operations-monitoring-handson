# AWS EKS Kubernetes監視・運用ハンズオン

このリポジトリは、Amazon EKSでPod、Node、ログ、メトリクス、イベント、権限まわりを初動確認するための受講者向けハンズオンです。

## 使い方

1. Section 2は、[固定データで行うKubernetes初動診断](labs/s2-kubernetes-initial-triage/README.md)から始めます。GitとPython 3.11以上があれば実行でき、AWSアカウントやクラスターは不要、費用は0円です。
2. AWS環境を使う後続演習では、先に[docs/prerequisites.md](docs/prerequisites.md)で必要なツールとAWSの利用境界を確認します。
3. [scripts/verify_prereqs.ps1](scripts/verify_prereqs.ps1)でPC側の準備状況を確認します。
4. 既存のEKSクラスターがある場合は、[scripts/collect_readonly_evidence.ps1](scripts/collect_readonly_evidence.ps1)で読み取り専用の状態確認を行います。
5. 講義に合わせて[labs](labs)配下の演習を進めます。Section 5 は、[Pod リソース問題の初動切り分け](labs/s5-pod-resource-first-response/README.md)で、許可された既存 EKS クラスターを読み取り専用で調べます。クラスター、権限、対象 Pod、Container Insights のデータがない場合も、固定済み合成データへ切り替えて同じ初動観点を再現できます。
6. AWS環境を利用した後は、[docs/cost-and-cleanup.md](docs/cost-and-cleanup.md)で残りリソースを確認します。

## 演習一覧

| 講義 | 演習 | ファイル |
| --- | --- | --- |
| s2-l3 | `kubectl get`に対応する固定データで全体を見る | [labs/s2-kubernetes-initial-triage/README.md](labs/s2-kubernetes-initial-triage/README.md) |
| s2-l4 | `describe`、`logs`、eventsに対応する固定データで深掘りする | [labs/s2-kubernetes-initial-triage/README.md](labs/s2-kubernetes-initial-triage/README.md) |
| s3-l4 | Container Insightsの画面を読む | [labs/03-container-insights.md](labs/03-container-insights.md) |
| s4-l2 / s4-l3 | 固定合成ログでCloudWatch Logs / Logs Insightsの絞り込みを練習する | [labs/s4-cloudwatch-logs-insights/README.md](labs/s4-cloudwatch-logs-insights/README.md) |
| s5-l3 / s5-l4 | 既存 EKS を読み取り専用で調べ、利用できない場合は固定データで Pending と CrashLoopBackOff を切り分ける | [labs/s5-pod-resource-first-response/README.md](labs/s5-pod-resource-first-response/README.md) |
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

このリポジトリは MIT License で提供します。条件は [LICENSE](LICENSE) を確認してください。
