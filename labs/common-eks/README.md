# 共通EKS基盤（AWS CloudShell / Bash）

このラボでは、Section 4とSection 5で使うEKSクラスタ1個とmanaged node 1台を東京リージョンへ作ります。AWS Management ConsoleからAWS CloudShellを開き、Bashで操作します。

## 前提条件と入力値

自分で利用を許可されたAWSアカウントを使い、東京リージョン `ap-northeast-1` のCloudShellを開きます。AWS CLI `2.12.3`以上、`kubectl`、`jq`が必要です。`kubectl`はcluster versionと同じ、または前後1 minor以内を使います。

```bash
export AWS_REGION="ap-northeast-1"
export AWS_DEFAULT_REGION="ap-northeast-1"
aws --version
kubectl version --client --output=json
jq --version
CALLER_ACCOUNT="$(aws sts get-caller-identity --region "$AWS_REGION" --query Account --output text --no-cli-pager)"
printf 'Caller account: %s\n' "$CALLER_ACCOUNT"
printf 'HOME=%s\n' "$HOME"
df -h "$HOME"
export AWS_ACCOUNT_ID="$CALLER_ACCOUNT"

export COMMON_EKS_DIR="$(pwd)"
chmod +x "$COMMON_EKS_DIR"/scripts/*.sh
CLOUDSHELL_PUBLIC_IP="$(curl -fsS https://checkip.amazonaws.com | tr -d '[:space:]')"
export API_PUBLIC_ACCESS_CIDR="${CLOUDSHELL_PUBLIC_IP}/32"
export AVAILABILITY_ZONE_A="ap-northeast-1a"
export AVAILABILITY_ZONE_B="ap-northeast-1c"
export CLEANUP_DEADLINE_UTC="$(date -u -d '+4 hours' '+%Y-%m-%dT%H:%M:%SZ')"
```

表示されたAWSアカウントが利用予定と異なる場合は停止してください。CloudShellの`$HOME`はRegionごとに1 GBです。`API_PUBLIC_ACCESS_CIDR`は現在のCloudShellのpublic IPv4だけを`/32`で指定し、`0.0.0.0/0`は使いません。削除開始は既定で4時間後です。15分より後、最大6時間以内を指定します。

## 費用

EKS control plane、`t3.medium` 1台、20 GiB gp3、public IPv4、CloudWatch Logsに料金が発生します。6時間の基礎概算は約USD 0.97ですが、利用時間、ログ量、税、割引などで実請求は変わります。実行直前に[Amazon EKS pricing](https://aws.amazon.com/eks/pricing/)、[Amazon EC2 On-Demand pricing](https://aws.amazon.com/ec2/pricing/on-demand/)、[CloudWatch pricing](https://aws.amazon.com/cloudwatch/pricing/)を確認してください。

## 作成手順

```bash
"$COMMON_EKS_DIR/scripts/preflight.sh"
"$COMMON_EKS_DIR/scripts/create.sh"
"$COMMON_EKS_DIR/scripts/status.sh"
```

同名の環境がある場合、scriptは更新せず停止します。期待結果:

- CloudFormation stack: `udemy4-c010-common-20260724`
- EKS cluster: `ACTIVE`
- private endpoint: `true`
- public endpoint: `true`、許可CIDRは現在のCloudShellの`/32`
- node group: `udemy4-c010-common-20260724-node`
- `kubectl get nodes`: 1 nodeが`Ready`

確認後、Section 5は`../s5-pod-resource-first-response/README.md`、Section 4は`../s4-cloudwatch-logs-insights/README.md`へ進みます。

## CloudShellのpublic IPv4が変わった場合

```bash
"$COMMON_EKS_DIR/scripts/recover-cidr.sh"
```

このscriptは対象を確認してから許可CIDRだけを現在のCloudShellの`/32`へ更新します。

## 削除手順

実行したSectionを先に削除します。Section 5を実行した場合:

```bash
cd ../s5-pod-resource-first-response
export S5_DIR="$(pwd)"
"$S5_DIR/scripts/cleanup-section.sh"
cd ../common-eks
```

Section 4を実行した場合はSection 4のREADMEにあるcleanupを完了してから戻ります。Section 5だけを実行した受講者がSection 4のcleanup commandを実行する必要はありません。

```bash
export COMMON_EKS_DIR="$(pwd)"
"$COMMON_EKS_DIR/scripts/delete.sh"
```

期待結果:

- Sectionで作成したリソースが残っていない。
- CloudFormation stackとEKS clusterが存在しない。
- EC2 instance、EBS volume、ENI、CloudWatch Logs、cleanup guardが残っていない。

残存、認証、権限、networkのエラーが表示された場合は、対象を確認して削除を完了してください。

## トラブルシュート

- `STS account does not equal AWS_ACCOUNT_ID`: AWSアカウントを確認し、`aws sts get-caller-identity`からやり直します。
- Regionの不一致: ConsoleとCloudShellを東京へ切り替えます。
- `kubectl context`: `aws eks update-kubeconfig --region ap-northeast-1 --name udemy4-c010-common-20260724`を実行します。
- `NodeCreationFailure`: Sectionへ進まず、CloudFormationの状態を確認して`scripts/delete.sh`を実行します。
- CloudShell切断: 同じRegionで開き、環境変数を再設定して`scripts/recover-cidr.sh`を実行します。
- 削除確認の失敗: 表示された残存や権限エラーを解決し、`scripts/delete.sh`を再実行します。

## 公式資料

- [AWS CloudShell concepts: Region and storage](https://docs.aws.amazon.com/cloudshell/latest/userguide/working-with-aws-cloudshell.html)
- [Connect kubectl to EKS with kubeconfig](https://docs.aws.amazon.com/eks/latest/userguide/create-kubeconfig.html)
- [Amazon EKS pricing](https://aws.amazon.com/eks/pricing/)
