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

`API_PUBLIC_ACCESS_CIDR`へ`0.0.0.0/0`は指定できません。templateは`EndpointPrivateAccess: true`と`EndpointPublicAccess: true`を併用し、public accessは上記exact CIDRへ限定します。これはrestricted public endpointだけでmanaged nodeがAPI serverへ到達できず`NodeCreationFailure`になった再発を防ぐためです。

`bind-current-identity.sh`はCourse/Section固定のGit外path `$HOME/eks-monitoring-private/c010-s4/current-run/current-sts-identity.json`を使います。初回の候補0件ではmode 700のtemporary sibling内でSTS取得・検証・writeを完了し、collisionを再確認してからno-clobber renameで`current-run`へinstallします。途中失敗ではtemporaryと空parentを回収するため、空の`current-run`を残しません。CloudShell再接続で環境変数が失われてもexact 1件を発見してcurrent STS identityを再検証し、同じfileを再利用します。候補が複数、foreign path、malformed、unexpected artifact、current identity mismatch、またはinstall中のcollisionなら新規作成・選択・上書きをせずfail closedです。内容をterminal、提出物、Issueへ貼り付けず、過去runとのaccount比較には使いません。

## 手順

### 1. fail-closed preflight

```bash
"$COMMON_EKS_DIR/scripts/preflight.sh"
```

現在のdefault CloudShell STS identityが有効であること、Region、AWS CLI/kubectl version、2 AZ、`t3.medium` offering、EKS quota、template、固定stack不存在、deadlineを確認します。成功表示にaccount IDは含めません。

### 2. cleanup guardとcommon EKSを作る

```bash
"$COMMON_EKS_DIR/scripts/create.sh"
```

guard stackを先に作り、exact bindingを確認してからcommon stackをatomicな`cloudformation create-stack`で一度だけ作り、`stack-create-complete`を待ちます。固定名stackが既に存在する場合は`AlreadyExists`で停止し、`deploy`、update、adoptを行いません。common stackの`update-stack`を使えるのは、下記のownership-bound CIDR recoveryだけです。common作成が途中で失敗してもguardは残ります。

guardのSchedulerはcommon stackの直接`DeleteStack`を呼びません。deadlineでexact Step Functions workflowだけを開始し、common stackがまだ`CREATE_IN_PROGRESS`なら固定Region・name・ownership・parametersを検証したまま有限の6時間timeout内で30秒ごとにsupported terminal stateを待ちます。その後workflowはcommon stackとEKSを照合してcleanup Lambdaを一時的にcommon VPCの2 subnetへattachします。LambdaのEKS access entryはcluster-admin policyを持たず、Kubernetes group `udemy4:c010:s4-cleanup`だけへ結合します。

RBACの適用境界は2つです。common `scripts/create.sh`はstack出力のcluster-scoped manifestだけを適用し、s4 namespace `udemy4-s4-logs`とs5 namespace `udemy4-c010-s5-20260724`それぞれに限定した`get/delete`のClusterRole/ClusterRoleBindingを再読込検証します。s4 workload flowはs4 namespaceを作成した後、Job作成前に別の完全manifestを適用し、namespaced Job `s4-log-generator`だけに限定したRole/RoleBindingを再読込検証します。common createはs4 namespaceやnamespaced Job RBACを先に作りません。scheduled cleanupはs4 namespaceが存在するときだけJobを確認・削除し、続いてs4 namespace、s5 namespace、exact log group、common stack、EC2/EBS/ENI/EKS log residualを順に確認してguardを最後に削除します。Lambdaは専用security groupとcontrol-plane ingressを使いprivate EKS endpointへ到達します。作成後は`aws eks update-kubeconfig`、exact context、1 Ready nodeを確認します。

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

このscriptは、先にexact guard stack、common stack ID/Region/name/tag、9個の固定parameter、EKS ARNのRegion/nameとtag、旧stack outputとruntimeの唯一の非world `/32`、private/public endpointを照合します。その後、現在のCloudShell IPv4を取得し、CloudFormationの`ApiPublicAccessCidr`だけを新しいexact `/32`へ更新します。他parameterは`UsePreviousValue=true`で保持し、`0.0.0.0/0`、複数CIDR、未知parameter、ownership不一致、unstable stackはfail closedです。update完了後にstack output、runtime endpoint、kubectl contextを再照合します。

deadline workflowはCloudShellのIPに依存しません。cleanup時だけLambdaをcommon VPCへattachし、AccessEntry groupとexact RBACでprivate endpointへ到達するため、session切断後もSection cleanup gateを省略しません。KubernetesがNamespaceへ自動付与する`kubernetes.io/metadata.name=udemy4-s4-logs`は必須system labelとして許可し、3個のownership label以外の追加user labelは拒否します。

## Cleanup

Section 4のREADMEに従ってSection namespaceとlog groupを先に削除します。その後、common EKSを削除します。

```bash
"$COMMON_EKS_DIR/scripts/delete.sh"
```

削除scriptはexact stackのRegion/name/tagを再照合し、次をfail closedで確認します。

1. common CloudFormation stackなし
2. EKS clusterなし
3. exact tagのEC2 instance、EBS volume、ENIなし
4. EKS descriptionのENIなし
5. `/aws/eks/udemy4-c010-common-20260724/` log groupなし
6. すべてpassした後だけguard stack、Scheduler schedule、Step Functions、cleanup Lambda/roleを削除

`create-stack`が失敗してcommon stackが`ROLLBACK_COMPLETE`、かつexact EKS clusterが不存在の場合だけ、failed-create recoveryへ分岐します。この分岐は`ap-northeast-1`、固定stack name/ARN構造、exact 5 tags、固定9 parameterのkey/valueと唯一の非world CIDR、exact `ROLLBACK_COMPLETE`を照合します。削除済みresource由来のoutputs、current CIDR、kubectl、Kubernetes contextは要求しません。`UPDATE_ROLLBACK_COMPLETE`など他status、tag/parameter/ARN drift、または同名EKS clusterが存在する場合は削除せず停止します。failed stackを削除した後もEC2/EBS/ENI/CloudWatch/EKS residual queryをすべて実行し、guardを最後に削除します。

`scripts/delete.sh`のmanual cleanup gateは、s4 exact namespace `udemy4-s4-logs`の不存在（namespace不在後はnamespaced Job endpointを照会しません）、s4 log group `/udemy4/c010/s4/20260725`の不存在、s5 exact namespace `udemy4-c010-s5-20260724`の不存在を確認してからcommon stackを削除し、同じprocess内で`scripts/verify-cleanup.sh`を実行します。scheduled cleanupも同じs4+s5境界を要求しますが、s4 namespaceが存在する間だけexact Job `s4-log-generator`を検査・削除します。`scripts/verify-cleanup.sh`だけの単独実行はSection residual gateを引き継げないためfail closedで停止します。common残存があればguardを削除せず、AWS CLIのpermission、credential、network errorを「不存在」として扱いません。

上記の成功表示後、post-guard verifierで同じcurrent identityを再検証し、guard削除後の全fixed residualをもう一度確認します。このscriptが成功した場合だけsole identity fileとprivate directoryを削除します。

```bash
"$COMMON_EKS_DIR/scripts/post-guard-verify.sh"
unset CURRENT_STS_IDENTITY_FILE PRIVATE_EXECUTION_DIR
```

途中でabortした場合もidentityを先に削除しません。現在identityを保持したままSection cleanup、common cleanup、残存0、guard-lastまで完了し、最後に`post-guard-verify.sh`を実行します。post-guard repeat zeroが失敗した場合はidentityを保持してfail closedになります。preflight中に作成前abortした場合も、固定resourceが不存在であることをcleanup手順とpost-guard verifierで確認してから破棄します。

## Troubleshooting

- `AWS_REGION ... ap-northeast-1`: ConsoleとCloudShell tabを東京へ切り替え、環境変数を再設定します。
- `kubectl context`: `aws eks update-kubeconfig --region ap-northeast-1 --name udemy4-c010-common-20260724`を実行し、exact ARNを確認します。
- `NodeCreationFailure`: Sectionへ進まず、guardを保持したままCloudFormationがexact `ROLLBACK_COMPLETE`になるまで待ち、`delete.sh`を実行します。clusterが不存在ならfailed-create recoveryがoutputs/kubectlなしでexact stackを削除し、残存確認後にguardを最後に削除します。他statusまたは同名clusterが残る場合はfail closedです。
- `Cleanup verification failed closed`: 表示されたexact残存だけを調査し、検査を削除・skipしません。
- fixed common stack `AlreadyExists`: scriptは既存stackをupdate/adoptしません。exact statusとownershipを確認し、作り直す場合はSection→common cleanupを完了してから新しいdeadlineでpreflightへ戻ります。CIDR driftだけは`scripts/recover-cidr.sh`を使います。
- CloudShell session切断: `$HOME`内のpackageとsole identityは同じRegionの次sessionでも残ります。Regionを再設定し、common directoryで`source scripts/bind-current-identity.sh`を実行してexact 1件を再発見・再検証します。新しいtimestamp directoryは作りません。その後`scripts/recover-cidr.sh`で現在IPへのexact recoveryを行い、deadlineと現存resourceを再確認します。deadline到達済みならguard workflowとresource状態を確認し、並行して手動cleanupを開始しません。

## 公式資料

- [AWS CloudShell concepts: Region and storage](https://docs.aws.amazon.com/cloudshell/latest/userguide/working-with-aws-cloudshell.html)
- [AWS CloudShell compute environment and pre-installed software](https://docs.aws.amazon.com/cloudshell/latest/userguide/vm-specs.html)
- [Connect kubectl to EKS with kubeconfig](https://docs.aws.amazon.com/eks/latest/userguide/create-kubeconfig.html)
- [EKS access policies and access entries](https://docs.aws.amazon.com/eks/latest/userguide/access-policies.html)
- [Lambda access to VPC resources](https://docs.aws.amazon.com/lambda/latest/dg/configuration-vpc.html)
- [EventBridge Scheduler starts Step Functions](https://docs.aws.amazon.com/step-functions/latest/dg/using-eventbridge-scheduler.html)
