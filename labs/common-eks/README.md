# 共通EKS基盤（Sections s2–s7）

`ap-northeast-1`に2 AZのpublic subnet、EKS cluster、1台の`ON_DEMAND t3.medium` managed node（20 GiB encrypted gp3）を作る短命な学習基盤です。NAT Gateway、Load Balancer、Container Insights、追加EBS volumeは作りません。

固定stack/cluster名は`udemy4-c010-common-20260724`、固定template contractは`udemy4-c010-common-eks-v2-20260724`です。stackとEKS clusterのownership tagは次の5個だけです。

- `Course=C010`
- `Lab=section-s5`
- `ManagedBy=udemy4`
- `Purpose=training`
- `TemplateContract=udemy4-c010-common-eks-v2-20260724`

## Fail-closed境界

- すべての外部scriptで`AWS_ACCOUNT_ID`を必須入力とし、STS結果との完全一致を確認します。値は公開ファイル、共有メモ、提出物へ保存しません。
- Regionは常に`ap-northeast-1`を明示し、Region endpointも確認します。
- 作成前に固定名stackが存在すれば、ownershipが一致していても更新・adoptせず停止します。
- `status.ps1`と`delete.ps1`は操作前にstack ARNのaccount/Region/name、5個だけのstack tag、`ClusterName`/`Region`/`TemplateContract` outputを再照合します。EKS clusterはARN、5個のownership tagに加え、CloudFormationが付与するsystem tag 3個だけを許可し、stack name、完全なstack ID、logical ID `EksCluster`へ完全一致させます。
- Kubernetes contextは`arn:aws:eks:ap-northeast-1:<AWS_ACCOUNT_ID>:cluster/udemy4-c010-common-20260724`との完全一致が必要です。substring一致は使用しません。
- 全AWS CLI / kubectl実行はexit codeを検査するwrapper経由です。not-foundを許す箇所はCloudFormation `ValidationError ... does not exist`またはEKS `ResourceNotFoundException`を明示解析し、認証、network、throttling等はempty扱いしません。
- API CIDRにdefaultはなく、`0.0.0.0/0`をtemplateとscriptで拒否します。

## 必須preflight入力

PowerShell 7、AWS CLI v2、`kubectl`、承認済みAWS認証が必要です。EKS control plane versionはtemplateで固定せず、実行時に利用可能な標準サポート版を使うため、作成直前にAWS公式情報と`kubectl`互換性を再確認します。scenario imageは`busybox:1.36.1`と`python:3.12-alpine`へtag固定されています。

次の5入力は毎回の実行shellだけに設定します。

```powershell
$env:AWS_ACCOUNT_ID = "<exact-12-digit-account-id>"
$env:API_PUBLIC_ACCESS_CIDR = "<trusted-public-ip>/32"
$env:AVAILABILITY_ZONE_A = "ap-northeast-1a"
$env:AVAILABILITY_ZONE_B = "ap-northeast-1c"
$env:CLEANUP_DEADLINE_UTC = [DateTimeOffset]::UtcNow.AddHours(4).ToString("yyyy-MM-dd'T'HH:mm:ss'Z'", [Globalization.CultureInfo]::InvariantCulture)
./scripts/preflight.ps1
```

例の式は実行時のUTCから4時間先をexact formatで設定します。deadlineは実行時刻より15分超先、かつ6時間以内のUTCでなければ拒否します。EKS作成時間と演習時間を考慮し、通常は2–5時間先にします。preflightは次を実値で検査します。

1. STS accountと必須account入力の一致。
2. `ap-northeast-1`と、選択した異なる2 AZの存在/available状態。
3. 両方の選択AZでの`t3.medium` offering。
4. EKS cluster quota値と現在cluster数を比較した1 cluster以上のheadroom。
5. CloudFormation templateのservice validation。
6. 固定common stackと固定guard stackの両方が存在しないこと。

callerにはCloudFormation、EKS、VPC/EC2、Service Quotas read、EventBridge Scheduler、IAM role作成、`iam:PassRole`、削除、残存確認に必要な権限が必要です。

## 作成

```powershell
./scripts/create.ps1
```

作成scriptもpreflightを再実行し、固定common stackと固定guard stackの不在をもう一度確認します。最初に外部guard stack `udemy4-c010-common-20260724-guard`を作成し、account/Region/name、5個のexact tag、5個のoutputをbindingしてからcommon stackを作成します。guard作成またはbindingが失敗すればcommon stack作成へ進みません。common stack作成や後続確認が失敗してもguardをrollback/deleteせず残します。`cloudformation deploy`を更新目的には使いません。

## Durable automatic cleanup guard

chargeableなcommon stackとは別の`cleanup-guard.yaml`を、common stackより先にCloudFormationで作ります。guard stackは必須deadlineにEventBridge Scheduler one-time scheduleを作ります。targetはuniversal AWS SDK `cloudformation:DeleteStack`で、専用roleが削除できるResourceは次のexact common stack ARNだけです。roleのtrustも`aws:SourceAccount`を現在account、`aws:SourceArn`を現在account/Regionのexact default schedule group ARNへ制限します。

`arn:aws:cloudformation:ap-northeast-1:<AWS_ACCOUNT_ID>:stack/udemy4-c010-common-20260724/*`

現在の`AWS::Scheduler::Schedule` CloudFormation resource schemaはScheduler APIの`ActionAfterCompletion`を公開していないため、その未対応propertyはguard templateへ記述しません。one-time targetの成否にかかわらず外部guard stackは残ります。`delete.ps1`はcommon stackが既にない場合も実行でき、common stack/EKS/課金対象残存の全queryが成功してemptyになった後だけ、exact guard bindingとschedule targetを再確認してguard stackを削除します。残存確認に失敗した場合はguardを削除しません。

## 状態確認

同じshellで少なくとも`AWS_ACCOUNT_ID`を設定し、exact kube contextを選んで実行します。

```powershell
./scripts/status.ps1
```

期待結果はCloudFormation `CREATE_COMPLETE`、EKS `ACTIVE`、node 1台が`Ready`です。bindingが1項目でも不一致なら状態表示を続けません。

## 費用

2026-07-24T07:00:00+09:00取得のTokyo単価は、EKS標準サポートUSD 0.10/cluster時、Linux `t3.medium` On-Demand USD 0.0544/時、gp3 USD 0.096/GB月、public IPv4 USD 0.005/IP時です。6時間の基礎概算は`6 × (0.10 + 0.0544 + 0.005) + 20 × 0.096 × 6/730` = 約USD 0.97です。

EventBridge Schedulerのone-time invocation、data transfer、CloudWatch、税、為替、pricing変更、追加resource、無料枠/割引はこの式に含めません。実請求は変わります。直前に[Amazon EKS pricing](https://aws.amazon.com/eks/pricing/)、[Amazon EC2 On-Demand pricing](https://aws.amazon.com/ec2/pricing/on-demand/)、[Amazon EBS pricing](https://aws.amazon.com/ebs/pricing/)、[Amazon VPC pricing](https://aws.amazon.com/vpc/pricing/)、[EventBridge Scheduler pricing](https://aws.amazon.com/eventbridge/pricing/)を再確認します。

## 手動削除と残存確認

Section namespace cleanup後、同じexact accountで実行します。

```powershell
./scripts/delete.ps1
```

scriptはcommon stackが存在すればbinding済みstack IDだけを削除し、`verify-cleanup.ps1`でstack、cluster、5 tag付きEC2/EBS/ENI、cluster descriptionのENI、cluster prefixのCloudWatch log groupを確認します。各queryが成功し、全結果がemptyの場合だけexact guardを削除し、guard stack、schedule、roleの消失も確認します。access/network/throttlingや不明なnot-foundは失敗です。wildcard deleteは行いません。

automatic guardが既にcommon stackを削除した場合も、同じaccount入力で同じcleanup入口を実行します。

```powershell
./scripts/delete.ps1
```

## 公式根拠

取得時刻: `2026-07-24T07:00:00+09:00`

- [EKS用VPCとpublic subnet](https://docs.aws.amazon.com/eks/latest/userguide/creating-a-vpc.html)
- [EKS network requirements](https://docs.aws.amazon.com/eks/latest/userguide/network-reqs.html)
- [EKS cluster IAM role](https://docs.aws.amazon.com/eks/latest/userguide/cluster-iam-role.html)
- [EKS node IAM role](https://docs.aws.amazon.com/eks/latest/userguide/create-node-role.html)
- [AWS::EKS::Cluster](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-eks-cluster.html)
- [AWS::EKS::Nodegroup](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-eks-nodegroup.html)
- [AWS::Scheduler::Schedule](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-scheduler-schedule.html)
