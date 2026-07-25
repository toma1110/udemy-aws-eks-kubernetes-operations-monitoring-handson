# Section 4: CloudWatch LogsとLogs Insights（AWS CloudShell / Bash）

対象は`s4-l2`「CloudWatch LogsでPodログを探す」と`s4-l3`「Logs Insightsの最初のクエリ」です。受講者向けの既定実行環境はAWS CloudShellのBashであり、local PowerShellは不要です。

## 目的

1. `udemy4-s4-logs` namespaceのexact Job/PodからJSON log 6件を取得する
2. fixed log group `/udemy4/c010/s4/20260725`へ同じ6件を送信し、readbackする
3. Logs Insightsを15分以内のwindowへ限定し、all-events 6件、ERROR 2件をexact namespace/Podへ結合して確認する
4. Section resourceをcommon EKSより先に削除し、namespace/Job/log groupの不存在を実APIで確認する

## 前提条件

- AWS Management Consoleで承認済みexact accountへsign inし、Region selectorで東京`ap-northeast-1`を選んで通常のCloudShellを開いている
- [common EKS README](../common-eks/README.md)のCloudShell preflight/create/statusが成功し、1 nodeが`Ready`
- common resourceのruntime ownership tagが`WorkPackage=c010-common-eks`
- AWS CLI `2.12.3`以上、`kubectl`、`jq`、Python 3がCloudShellで利用できる
- packageとevidence用の空きがCloudShellのRegion別`$HOME` 1 GB内にある
- common EKSを含む総利用時間は4時間を既定、最大6時間以内とする

最初にpreauthenticated identity、Region、version、storageを確認します。account出力が承認済みexact accountと一致しない場合は停止してください。

```bash
export AWS_REGION="ap-northeast-1"
export AWS_DEFAULT_REGION="ap-northeast-1"

aws --version
kubectl version --client --output=json
jq --version
aws configure list
df -h "$HOME"

CALLER_ACCOUNT="$(aws sts get-caller-identity \
  --region "$AWS_REGION" \
  --query Account \
  --output text \
  --no-cli-pager)"
printf 'Caller account: %s\n' "$CALLER_ACCOUNT"

# 表示accountを承認済みexact accountと照合してからbindする
export AWS_ACCOUNT_ID="$CALLER_ACCOUNT"
```

AWS CLIが`2.12.3`未満、`kubectl`がcluster versionと同じまたは前後1 minor以内でない、storageが不足している場合は実行しません。scriptはこれらをsemantic versionとして比較します。

## Cost warning

このSectionはCloudWatch Logs ingestionとLogs Insights scanを追加します。2026-07-25にAWS Price List APIで確認した東京Regionの標準custom log ingestionはUSD 0.76/GB、Logs Insights scanはUSD 0.0076/GBです。6件の短いsample logは小容量ですが、common EKS、EC2、EBS、public IPv4の料金はcleanupまで続きます。料金は変わり得るため、実行直前に[CloudWatch pricing](https://aws.amazon.com/cloudwatch/pricing/)と[Amazon EKS pricing](https://aws.amazon.com/eks/pricing/)を確認してください。実請求はtax、discount、Free Tier、billing granularityで異なります。

## Setup

CloudShellでこのpublic repositoryをcloneし、Section 4 directoryへ移動します。すでにclone済みなら`git clone`は繰り返さず、既存checkoutで`cd`から始めます。`LEARNER_REPO`はこのpackageを含むexact Git worktree rootです。evidenceはGit worktree外の`$HOME`へ置きます。

```bash
cd "$HOME"
if [[ ! -d udemy-aws-eks-kubernetes-operations-monitoring-handson ]]; then
  git clone https://github.com/toma1110/udemy-aws-eks-kubernetes-operations-monitoring-handson.git
fi
cd "$HOME/udemy-aws-eks-kubernetes-operations-monitoring-handson/labs/s4-cloudwatch-logs-insights"

export S4_DIR="$(pwd -P)"
export LEARNER_REPO="$(git -C "$S4_DIR" rev-parse --show-toplevel)"
export EVIDENCE_DIR="$HOME/eks-monitoring-evidence/s4-cloudwatch-logs"
CLOUDSHELL_PUBLIC_IP="$(curl -fsS https://checkip.amazonaws.com | tr -d '[:space:]')"
export API_PUBLIC_ACCESS_CIDR="${CLOUDSHELL_PUBLIC_IP}/32"
mkdir -p "$EVIDENCE_DIR"
chmod +x "$S4_DIR"/scripts/*.sh
```

`API_PUBLIC_ACCESS_CIDR`はcommon EKS stackの`ApiPublicAccessCidr` output、runtime clusterの唯一の`publicAccessCidrs`、現在のCloudShell public IPv4 `/32`のすべてと一致する必要があります。CloudShellへ再接続してIPが変わった場合はSectionを実行せず、common EKS directoryの`scripts/recover-cidr.sh`でexact ownership-bound updateを完了してから再確認します。`0.0.0.0/0`、複数CIDR、未知parameterやstackのadoptionは受理しません。

`EVIDENCE_DIR`がGit worktree内、relative path、または別Git worktree内ならscriptは停止します。evidenceにはquery IDや結果が含まれます。account ID、ARN、credentialは保存しません。

## 手順

### 1. Section preflight

```bash
"$S4_DIR/scripts/preflight.sh"
```

期待結果: exact account、東京Region、common cluster ARN、common stackのexact 5 tags、EKSのCloudFormation system tagsを含むexact 8 tags、固定`ClusterName`/`Region`/`TemplateContract` outputs、private/restricted-public endpoint、kubectl contextが一致し、fixed namespaceとlog groupが存在しません。tag/output drift、欠落、余分なtagはmutation前にfail closedです。

### 2. sample workloadを実行

```bash
"$S4_DIR/scripts/apply-workload.sh"
```

scriptはnamespaceを新規作成した直後、common stack outputに結合されたleast-privilege RBACを適用・再読込検証してからJobを作ります。cleanup roleのAccessEntryはKubernetes group `udemy4:c010:s4-cleanup`だけを持ち、RBACはnamespaced Job `s4-log-generator`とcluster-scoped Namespace `udemy4-s4-logs`の`get/delete`だけを`resourceNames`で許可します。cluster-admin policyは使いません。その後、Job labelで選択されるPodがexactly 1で、そのPodがexact Job UIDのcontroller ownerを持つことを確認します。Pod logはexactly 6 JSON rowsで、全行の`namespace`と`pod`がruntime値に一致しなければ停止します。

期待するlevel内訳:

- `INFO`: 3
- `WARN`: 1
- `ERROR`: 2

### 3. CloudWatch Logsへ送信し、readbackする（s4-l2）

```bash
"$S4_DIR/scripts/publish-logs.sh"
```

作成対象:

- log group: `/udemy4/c010/s4/20260725`
- log stream: `sample-workload`
- retention: 1 day
- tags: `Course=C010`, `Section=s4`, `ManagedBy=udemy4`, `Purpose=training`

`PutLogEvents`の`rejectedLogEventsInfo`がないこと、`GetLogEvents`がexactly 6件を返し、messageがPod log 6件と一致することを確認します。query windowは最初/最後のeventの前後2分、最大15分です。

AWS Consoleでも東京Regionを再確認し、CloudWatch > Log groups > `/udemy4/c010/s4/20260725` > `sample-workload`を開きます。namespace、Pod名、時間帯を手がかりに6件が見えることを確認します。実Console結果はlive実行後にだけevidenceとして扱います。

### 4. Logs Insights queryを実行（s4-l3）

```bash
"$S4_DIR/scripts/query-logs.sh"
```

実行するquery:

- [queries/all-events.logs-insights](queries/all-events.logs-insights): exact namespaceとruntime Job Pod prefixへ限定し、6件
- [queries/errors.logs-insights](queries/errors.logs-insights): 同じscopeで`ERROR`だけ2件

両queryともstatusが`Complete`でなければ失敗です。decoded rowのnamespace/Pod、ERROR queryのlevel、exact 6/2 countを検証し、raw results、decoded results、`recordsMatched`、`bytesScanned`を`EVIDENCE_DIR`へ保存します。

Logs Insights Consoleで同じlog groupと保存済みwindowを選び、query fileの内容を実行すると、時系列、namespace、exact Podを画面上でも確認できます。Consoleやserviceの実結果を生成画像・fixtureで代用しません。

## 期待結果

| Check | Expected |
| --- | --- |
| Runtime Job Pod | exact Job label/UIDに結合した1 Pod |
| Job log | 6 rows、runtime namespace/Pod一致 |
| CloudWatch readback | 6 rows、message集合一致 |
| all-events query | `Complete`、6 rows |
| errors query | `Complete`、2 `ERROR` rows |
| Query range | 0秒超、900秒以下 |
| Evidence | raw/decoded resultとscan statistics。credential/account identityなし |

このrevised CloudShell/Bash routeはlocalのsyntax/fixture validationだけを通過しており、成功したlive AWS runとして扱わないでください。

## Cleanup

必ずSectionを先に削除し、その後common EKSを削除します。

```bash
"$S4_DIR/scripts/cleanup-section.sh"
```

Section cleanupはnamespace/Jobのexact name・namespaceと完全なlabel map、log groupのexact tagsを確認してから削除します。Namespaceは3 ownership labelsとKubernetes mandatory `kubernetes.io/metadata.name=udemy4-s4-logs`だけ、Jobは3 ownership labelsだけを許可します。未知labelが1つでもあれば削除せず停止します。その後、namespace/Jobとfixed log groupの不存在を実APIで確認します。AccessDenied、expired credential、network errorを「不存在」として扱いません。

次にcommon READMEのdirectoryへ移動し、common stackとguardを削除します。

```bash
export COMMON_EKS_DIR="../common-eks"
"$COMMON_EKS_DIR/scripts/delete.sh"
```

common cleanupではCloudFormation、EKS、EC2、EBS、ENI、cluster log groupの残存queryがすべてpassした後だけguardを最後に削除します。deadline到達時はSchedulerが直接common stackを削除せず、Step Functionsがcleanup Lambdaを一時的にcommon VPCへattachし、AccessEntry groupとresourceName限定RBACでprivate endpointからexact Job/namespaceを削除・確認します。Namespaceの3 ownership labelsに加え、Kubernetesが必ず付ける`kubernetes.io/metadata.name=udemy4-s4-logs`だけをsystem labelとして許可し、未知user labelは拒否します。その後、Lambda detach、log group、common、residual、guardの順を維持します。`$HOME` 1 GBを圧迫しないよう、必要なevidenceをdownloadした後に不要なlocal copyを削除します。

## Fixture fallback

fixtureはfilter/schemaのsafe local regressionだけに使えます。CloudWatch service、actual account、IAM、EKS、料金、Console結果を証明しません。

```bash
python3 -B "$S4_DIR/analyze.py" --check
python3 -B -m unittest discover -s "$S4_DIR/tests" -p 'test_*.py'
```

live AWS実行ができない場合は、理由を記録してfixture確認までで停止し、live成功とは表現しません。

## Troubleshooting

- `STS account does not equal AWS_ACCOUNT_ID`: Consoleのaccountを確認し、承認済みexact accountへ切り替えます。
- Region error: Console selector、CloudShell tab、`AWS_REGION`、`AWS_DEFAULT_REGION`をすべて`ap-northeast-1`へ合わせます。
- kubectl context error: common READMEに従い`aws eks update-kubeconfig --region ap-northeast-1 --name udemy4-c010-common-20260724`を実行します。
- Pod count/owner error: resourceをadoptせず、Section cleanup後にpreflightからやり直します。
- queryが`Complete`にならない: statusを保存して停止し、time range、log group、Region、permissionを確認します。
- cleanup failure: exact residualを確認し、検査をskipしません。common cleanupはSection cleanup pass後にだけ行います。
- manual cleanup ownership label mismatch: 追加labelを無視して削除しません。Namespace/Jobの作成元とownershipを調査し、exact mapへ戻す判断なしにlabelを削除・上書きしません。
- CloudShell再接続: 同じRegionの`$HOME` fileは残りますがsession環境変数は再設定が必要です。STS、Region、deadline、resource statusを再確認します。

## 公式資料

- [AWS CloudShell concepts](https://docs.aws.amazon.com/cloudshell/latest/userguide/working-with-aws-cloudshell.html)
- [AWS CloudShell compute environment](https://docs.aws.amazon.com/cloudshell/latest/userguide/vm-specs.html)
- [Connect kubectl to EKS with kubeconfig](https://docs.aws.amazon.com/eks/latest/userguide/create-kubeconfig.html)
