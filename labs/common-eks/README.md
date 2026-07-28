# 共通EKS基盤（AWS CloudShell / Bash）

このラボでは、東京リージョンに短時間だけEKSクラスター1個とmanaged node 1台を作ります。AWS Management ConsoleからAWS CloudShellを開き、Bashで操作します。

## 作成するもの

- EKSクラスター `udemy4-c010-common-20260724`
- managed node 1台
- CloudShellから接続するための、現在のpublic IPv4だけを許可したEKS API接続
- 4時間後に削除を開始するcleanup guard

EKS APIはVPC内からも接続できる設定にし、外部からの接続はCloudShellの現在のIPv4 1個に限定します。Sectionのリソースを先に削除し、その後で共通EKSとcleanup guardを削除します。

## 前提条件

1. hands-on用として使用を許可されたAWSアカウントへsign inします。
2. Console右上で東京（`ap-northeast-1`）を選び、CloudShellを開きます。
3. Bashで次を実行します。

```bash
export AWS_REGION="ap-northeast-1"
export AWS_DEFAULT_REGION="ap-northeast-1"

aws --version
kubectl version --client --output=json
jq --version
aws configure list

CALLER_ACCOUNT="$(aws sts get-caller-identity \
  --region "$AWS_REGION" \
  --query Account \
  --output text \
  --no-cli-pager)"
printf 'Caller account: %s\n' "$CALLER_ACCOUNT"

# 表示された値が使用を許可されたアカウントと一致してから設定する
export AWS_ACCOUNT_ID="$CALLER_ACCOUNT"
```

AWS CLIは`2.12.3`以上、`kubectl`はクラスターと同じ、または前後1 minor以内を使います。条件を満たさない場合は、ツールを更新してから進めます。

CloudShellの`$HOME`はリージョンごとに1 GBです。空き容量を確認します。

```bash
printf 'HOME=%s\n' "$HOME"
df -h "$HOME"
```

容量が少ない場合は不要ファイルを整理してから進めます。

## 料金の注意

EKS control plane、`t3.medium` 1台、20 GiB gp3、public IPv4、CloudWatch Logsに料金が発生します。cleanup guardにも少額のScheduler、Step Functions、Lambda料金が発生します。利用時間、データ量、税、割引などで実際の請求額は変わります。

実行直前に[Amazon EKS pricing](https://aws.amazon.com/eks/pricing/)、[AWS Lambda pricing](https://aws.amazon.com/lambda/pricing/)、[AWS Step Functions pricing](https://aws.amazon.com/step-functions/pricing/)、[Amazon EC2 On-Demand pricing](https://aws.amazon.com/ec2/pricing/on-demand/)、[CloudWatch pricing](https://aws.amazon.com/cloudwatch/pricing/)を確認してください。最大6時間以内に削除を始めます。

## 準備

このREADMEがあるディレクトリで実行します。

```bash
export COMMON_EKS_DIR="$(pwd)"
chmod +x "$COMMON_EKS_DIR"/scripts/*.sh

CLOUDSHELL_PUBLIC_IP="$(curl -fsS https://checkip.amazonaws.com | tr -d '[:space:]')"
export API_PUBLIC_ACCESS_CIDR="${CLOUDSHELL_PUBLIC_IP}/32"
export AVAILABILITY_ZONE_A="ap-northeast-1a"
export AVAILABILITY_ZONE_B="ap-northeast-1c"

# 既定は4時間後。15分超、最大6時間以内を指定する
export CLEANUP_DEADLINE_UTC="$(date -u -d '+4 hours' '+%Y-%m-%dT%H:%M:%SZ')"
```

`API_PUBLIC_ACCESS_CIDR`に`0.0.0.0/0`は指定できません。

## 作成手順

### 1. 作成前の確認

```bash
"$COMMON_EKS_DIR/scripts/preflight.sh"
```

AWSアカウント、東京リージョン、ツールのバージョン、利用するAZ、インスタンスタイプ、EKS quota、設定、削除予定時刻を確認します。エラーが表示された場合は、該当する設定を確認してから再実行してください。

### 2. cleanup guardと共通EKSを作成する

```bash
"$COMMON_EKS_DIR/scripts/create.sh"
```

cleanup guardを先に作り、その後で共通EKSを作ります。同名の環境がすでにあるというメッセージが表示された場合は、新しく作成せず、`status.sh`で対象を確認してください。作成に失敗した場合もcleanup guardは残るため、トラブルシュート後に残存を確認して削除します。

### 3. 状態を確認する

```bash
"$COMMON_EKS_DIR/scripts/status.sh"
```

期待結果:

- CloudFormation stack: `udemy4-c010-common-20260724`
- EKS cluster: `ACTIVE`
- private endpoint: `true`
- public endpoint: `true`で、許可範囲はCloudShellの現在の`/32`
- node group: `udemy4-c010-common-20260724-node`
- `kubectl get nodes`: 1 nodeが`Ready`

すべて成功した後だけSectionのhands-onへ進みます。

## CloudShellのpublic IPv4が変わった場合

CloudShellへ再接続するとpublic IPv4が変わることがあります。共通EKSのディレクトリで次を実行します。

```bash
"$COMMON_EKS_DIR/scripts/recover-cidr.sh"
```

このスクリプトはAWSアカウント、東京リージョン、対象リソース、現在の接続設定を確認し、CloudShellからの接続に使う`/32`だけを現在のIPv4へ更新します。エラーが表示された場合は、アカウント、リージョン、対象リソースを確認してから再実行してください。

## 削除

先に、実行した各SectionのREADMEにあるSection用cleanupを完了します。Section 2では次を実行します。

```bash
bash labs/s2-kubernetes-baseline/scripts/cleanup-section.sh
```

Sectionのリソースがないことを確認できた後で、共通EKSを削除します。

```bash
"$COMMON_EKS_DIR/scripts/delete.sh"
```

削除後は次が残っていないことを確認します。

1. 共通CloudFormation stack
2. EKS cluster
3. このラボで作成したEC2 instance、EBS volume、ENI
4. EKSのENI
5. `/aws/eks/udemy4-c010-common-20260724/` log group
6. cleanup guard

残存や認証、ネットワーク、権限のエラーが表示された場合は、cleanup guardを残したまま原因を解決し、もう一度削除と残存確認を実行してください。

## トラブルシュート

- `STS account does not equal AWS_ACCOUNT_ID`: AWSアカウントを確認し、`aws sts get-caller-identity`からやり直します。
- Regionの不一致: ConsoleとCloudShellを東京へ切り替え、環境変数を再設定します。
- `kubectl context`: `aws eks update-kubeconfig --region ap-northeast-1 --name udemy4-c010-common-20260724`を実行し、接続先を確認します。
- `NodeCreationFailure`: Sectionへ進まず、CloudFormationの状態と対象のスタック名を確認してから`delete.sh`を実行します。
- 削除確認の失敗: 表示された残存、権限、認証、ネットワークを確認し、検査を省略しません。
- 同名環境がある: 既存環境を自動変更しません。不要であることを確認できた場合だけ、Sectionから順に削除して作り直します。
- CloudShell切断: 同じリージョンでCloudShellを開き、環境変数を再設定します。`recover-cidr.sh`を実行し、削除予定時刻とリソースの状態を確認します。

## 公式資料

- [AWS CloudShell concepts: Region and storage](https://docs.aws.amazon.com/cloudshell/latest/userguide/working-with-aws-cloudshell.html)
- [AWS CloudShell compute environment and pre-installed software](https://docs.aws.amazon.com/cloudshell/latest/userguide/vm-specs.html)
- [Connect kubectl to EKS with kubeconfig](https://docs.aws.amazon.com/eks/latest/userguide/create-kubeconfig.html)
- [EKS access policies and access entries](https://docs.aws.amazon.com/eks/latest/userguide/access-policies.html)
- [Lambda access to VPC resources](https://docs.aws.amazon.com/lambda/latest/dg/configuration-vpc.html)
- [EventBridge Scheduler starts Step Functions](https://docs.aws.amazon.com/step-functions/latest/dg/using-eventbridge-scheduler.html)
