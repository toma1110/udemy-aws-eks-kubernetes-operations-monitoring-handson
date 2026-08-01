# Common EKS foundation（AWS CloudShell / Bash）

この共通labは、Section 4を含むEKS hands-on用に、東京Regionへ短時間だけ1 cluster・1 managed nodeを作ります。AWS Management ConsoleからAWS CloudShellを開き、表示されたBash promptでコマンドを実行します。local PowerShellは不要です。

## 目的

- `ap-northeast-1`へ実行Regionを固定する
- `udemy4-c010-common-20260724`を固定名・固定tagで作る
- runtime ownership tag `WorkPackage=c010-common-eks`でcommon resourceを一貫して識別する
- managed nodeからEKS API serverへVPC内で到達できるprivate endpointを使いながら、public endpointはCloudShellのexact `/32`だけに制限する
- 4時間後のcleanup guardを先に作り、CloudShell切断後もexact Section→common→guard cleanup workflowを最大6時間以内に開始する
- Section resourceを先に削除した後、EKS・EC2・EBS・ENI・CloudWatchの残存を確認し、guardを最後に削除する

## 前提条件

1. AWS Management Consoleへsign inします。
2. Console右上のRegion selectorで**東京 `ap-northeast-1`**を選び、CloudShellを開きます。CloudShellのterminal tabにも東京Regionが表示されることを確認します。
3. Bash promptで次を実行します。

```bash
export AWS_REGION="ap-northeast-1"
export AWS_DEFAULT_REGION="ap-northeast-1"

aws --version
kubectl version --client --output=json
jq --version
aws configure list
```

AWS CLIは`2.12.3`以上、`kubectl`はcluster versionと同じ、または前後1 minor以内を使います。scriptは表示文字列ではなくsemantic versionとして比較し、version条件を満たさない場合は作成を始めません。

CloudShellの`$HOME`はRegionごとに1 GBの永続領域です。作業fileと後で使うevidenceは`$HOME`配下へ置き、容量を確認します。VPC environmentではpersistent storageを利用できないため、このlabは通常のCloudShell environmentから開始します。

```bash
printf 'HOME=%s\n' "$HOME"
df -h "$HOME"
```

1 GBに近い場合は不要fileを整理してから進めます。downloadが必要なevidenceはcleanup後に回収し、不要になったlocal copyも削除します。

## Cost warning

EKS control plane、`t3.medium` 1台、20 GiB gp3、public IPv4、CloudWatch Logsに料金が発生します。2026-07-25にAWS Price List APIで確認した6時間のEKS/EC2/EBS/public IPv4 subtotal概算は約USD 0.97です。cleanup guardはScheduler、Step Functions、短時間のLambdaを追加するため、そのrequest/execution料金も発生します。guardはNAT Gateway、専用EIP、常時実行computeを作りません。Section 4ではさらにlog ingestionとLogs Insights scanが発生します。実請求は利用時間、request/state transition、data量、tax、discount、Free Tier、meteringで変わります。実行直前に[Amazon EKS pricing](https://aws.amazon.com/eks/pricing/)、[AWS Lambda pricing](https://aws.amazon.com/lambda/pricing/)、[AWS Step Functions pricing](https://aws.amazon.com/step-functions/pricing/)、[Amazon EC2 On-Demand pricing](https://aws.amazon.com/ec2/pricing/on-demand/)、[CloudWatch pricing](https://aws.amazon.com/cloudwatch/pricing/)を確認してください。

## Setup

このREADMEがあるdirectoryを`COMMON_EKS_DIR`へ設定します。packageはCloudShellの`$HOME`配下に置きます。

```bash
export COMMON_EKS_DIR="$(pwd)"
chmod +x "$COMMON_EKS_DIR"/scripts/*.sh
source "$COMMON_EKS_DIR/scripts/bind-current-identity.sh"

CLOUDSHELL_PUBLIC_IP="$(curl -fsS https://checkip.amazonaws.com | tr -d '[:space:]')"
export API_PUBLIC_ACCESS_CIDR="${CLOUDSHELL_PUBLIC_IP}/32"
export AVAILABILITY_ZONE_A="ap-northeast-1a"
export AVAILABILITY_ZONE_B="ap-northeast-1c"

# 既定は4時間後。scriptは15分超、最大6時間以内だけを受理する
export CLEANUP_DEADLINE_UTC="$(date -u -d '+4 hours' '+%Y-%m-%dT%H:%M:%SZ')"
```

`API_PUBLIC_ACCESS_CIDR`へ`0.0.0.0/0`は指定できません。private endpointを有効にし、public endpointはCloudShellの`/32`だけに限定します。これにより、nodeからAPI serverへ到達できる経路を残しながら、public accessを広げません。

`bind-current-identity.sh`は、現在のAWS identityをGit管理外のprivate file `$HOME/eks-monitoring-private/c010-s4/current-run/current-sts-identity.json`へ保存します。CloudShellへ再接続した場合は同じfileを再検証して使います。

- identity fileの内容をterminal、提出物、Issueへ貼り付けないでください。
- 候補が複数ある、fileが壊れている、現在のidentityと一致しない場合は処理が停止します。新しいfileを手作業で選んだり上書きしたりしないでください。

## 手順

### 1. 作成前の安全確認

```bash
"$COMMON_EKS_DIR/scripts/preflight.sh"
```

現在のCloudShell identity、Region、AWS CLIとkubectlのversion、2つのAvailability Zone、`t3.medium`、EKS quota、template、同名stackの不存在、cleanup期限を確認します。成功表示にaccount IDは含めません。

### 2. cleanup guardとcommon EKSを作る

```bash
"$COMMON_EKS_DIR/scripts/create.sh"
```

cleanup guardを先に作り、その後common EKS stackを1回だけ作成して完了を待ちます。同名stackがある場合は`AlreadyExists`で停止し、既存stackを変更または流用しません。例外は、後述するCloudShell public IP変更時のCIDR更新だけです。作成が途中で失敗してもcleanup guardは残ります。

期限に達するとSchedulerがStep Functionsのcleanup workflowを開始します。stack作成中なら最大6時間待ち、完了後に対象stackとEKS clusterを確認してからcleanup Lambdaを一時的にVPCへ接続します。Lambdaにはcluster-adminを与えず、cleanup専用のKubernetes groupだけを使います。

cleanup権限はSection 4とSection 5のnamespaceだけに限定します。Section 4のJob削除権限も`udemy4-s4-logs`内の`udemy4-s4-log-generator`だけが対象です。

作成後は次を確認します。

- `aws eks update-kubeconfig`が成功する
- 接続先がこの演習のclusterである
- nodeが1台`Ready`になっている

### 3. statusを確認する

```bash
"$COMMON_EKS_DIR/scripts/status.sh"
```

期待結果:

- CloudFormation stack: `udemy4-c010-common-20260724`
- EKS cluster: `ACTIVE`
- endpoint: private `true`、public `true`、public CIDRはCloudShellのexact `/32`
- node group: `udemy4-c010-common-20260724-node`
- `kubectl get nodes`: 1 nodeが`Ready`

ここまで成功した後だけSection hands-onへ進みます。

## CloudShell public IP変更時のrecovery

CloudShellへ再接続してpublic IPv4が変わると、旧`/32`に限定されたpublic endpointへ現在sessionから到達できません。`API_PUBLIC_ACCESS_CIDR`を書き換えて検査を回避せず、common directoryで次を実行します。

```bash
"$COMMON_EKS_DIR/scripts/recover-cidr.sh"
```

このscriptは対象stackとEKS clusterのRegion、名前、tag、parameterを確認し、`ApiPublicAccessCidr`だけを現在のCloudShell IPv4の`/32`へ更新します。ほかのparameterは変更しません。`0.0.0.0/0`、複数CIDR、所有者が一致しないstack、不安定なstackは拒否されます。更新後にendpointとkubectlの接続先を再確認します。

期限によるcleanupはCloudShellのIPに依存しません。cleanup Lambdaはprivate endpointを使うため、CloudShell sessionが切れてもSectionのresourceを確認してから削除します。

## Cleanup

Section 4のREADMEに従ってSection namespaceとlog groupを先に削除します。その後、common EKSを削除します。

```bash
"$COMMON_EKS_DIR/scripts/delete.sh"
```

削除scriptは対象stackのRegion、名前、tagを確認し、次のresourceが残っていないことを確認します。

1. common CloudFormation stackなし
2. EKS clusterなし
3. exact tagのEC2 instance、EBS volume、ENIなし
4. EKS descriptionのENIなし
5. `/aws/eks/udemy4-c010-common-20260724/` log groupなし
6. すべて確認できた後だけguard stack、Scheduler、Step Functions、cleanup Lambdaとroleを削除

作成に失敗したstackは、状態が`ROLLBACK_COMPLETE`で同名EKS clusterが存在しない場合だけ削除できます。ほかの状態、tagやparameterの不一致、同名clusterの存在を検出した場合は削除せず停止します。失敗したstackを削除した後も、EC2、EBS、ENI、CloudWatch Logs、EKSの残存を確認し、cleanup guardは最後に削除します。

`scripts/delete.sh`は、Section 4のnamespaceとlog group、Section 5のnamespaceが削除済みであることを確認してからcommon stackを削除します。続けて`scripts/verify-cleanup.sh`を自動実行します。この確認scriptだけを単独実行しないでください。

resourceが残っている場合や、AWS CLIの権限、credential、networkに問題がある場合はcleanup guardを削除しません。エラーを「resourceなし」と読み替えず、表示された原因を解消してください。

上記の成功表示後、同じidentityでresourceが残っていないことをもう一度確認します。この確認に成功した場合だけprivate identity fileを削除します。

```bash
"$COMMON_EKS_DIR/scripts/post-guard-verify.sh"
unset CURRENT_STS_IDENTITY_FILE PRIVATE_EXECUTION_DIR
```

途中で停止した場合もidentity fileを先に削除しません。Section、common EKS、cleanup guardの順に片付け、最後に`post-guard-verify.sh`を実行します。確認に失敗した場合はidentity fileを残し、表示されたresourceまたは接続エラーを調査します。

## Troubleshooting

- `AWS_REGION ... ap-northeast-1`: ConsoleとCloudShell tabを東京へ切り替え、環境変数を再設定します。
- `kubectl context`: `aws eks update-kubeconfig --region ap-northeast-1 --name udemy4-c010-common-20260724`を実行し、exact ARNを確認します。
- `NodeCreationFailure`: Sectionへ進まず、cleanup guardを残したままCloudFormationが`ROLLBACK_COMPLETE`になるまで待ち、`delete.sh`を実行します。同名clusterが残る場合は自動削除せず停止します。
- cleanup確認の失敗: 表示された残存resourceまたは接続エラーを調査し、確認手順を省略しないでください。
- fixed common stack `AlreadyExists`: scriptは既存stackをupdate/adoptしません。exact statusとownershipを確認し、作り直す場合はSection→common cleanupを完了してから新しいdeadlineでpreflightへ戻ります。CIDR driftだけは`scripts/recover-cidr.sh`を使います。
- CloudShell session切断: `$HOME`内のpackageとsole identityは同じRegionの次sessionでも残ります。Regionを再設定し、common directoryで`source scripts/bind-current-identity.sh`を実行してexact 1件を再発見・再検証します。新しいtimestamp directoryは作りません。その後`scripts/recover-cidr.sh`で現在IPへのexact recoveryを行い、deadlineと現存resourceを再確認します。deadline到達済みならguard workflowとresource状態を確認し、並行して手動cleanupを開始しません。

## 公式資料

- [AWS CloudShell concepts: Region and storage](https://docs.aws.amazon.com/cloudshell/latest/userguide/working-with-aws-cloudshell.html)
- [AWS CloudShell compute environment and pre-installed software](https://docs.aws.amazon.com/cloudshell/latest/userguide/vm-specs.html)
- [Connect kubectl to EKS with kubeconfig](https://docs.aws.amazon.com/eks/latest/userguide/create-kubeconfig.html)
- [EKS access policies and access entries](https://docs.aws.amazon.com/eks/latest/userguide/access-policies.html)
- [Lambda access to VPC resources](https://docs.aws.amazon.com/lambda/latest/dg/configuration-vpc.html)
- [EventBridge Scheduler starts Step Functions](https://docs.aws.amazon.com/step-functions/latest/dg/using-eventbridge-scheduler.html)
