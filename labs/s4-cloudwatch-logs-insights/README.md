# Section 4: CloudWatch LogsとLogs Insights（AWS CloudShell / Bash）

このハンズオンでは、EKS上のPodが出したログをCloudWatch Logsへ送り、Logs Insightsで必要な行を探します。対象講義は`s4-l2`「CloudWatch LogsでPodログを探す」と`s4-l3`「Logs Insightsの最初のクエリ」です。操作はAWS CloudShellのBashで行うため、local PowerShellは不要です。

## 目的

次の流れを、自分で実行して確認できるようになることが目標です。

1. EKSのsample Jobから6件のJSONログを取得する
2. CloudWatch Logsで、Region、log group、時間帯、Pod名を手がかりに6件を見つける
3. Logs Insightsで全6件とERROR 2件へ絞り込む
4. 学習用resourceを安全な順番で削除し、残っていないことを確認する

## 前提条件

- AWS Management Consoleへsign inしている
- ConsoleのRegion selectorで東京`ap-northeast-1`を選び、通常のAWS CloudShellを開いている
- [common EKS README](../common-eks/README.md)のpreflight、create、statusを完了し、nodeが1台`Ready`になっている
- AWS CLI `2.12.3`以上、`kubectl`、`jq`、Python 3をCloudShellで利用できる
- CloudShellのRegion別`$HOME`（1 GB）に、repositoryと結果保存用の空きがある
- common EKSを含む総利用時間を通常4時間、最大6時間以内に収められる

最初に知っておく用語は4つです。

- Namespace（名前空間）: Kubernetes resourceを学習単位に分ける入れ物。この演習では`udemy4-s4-logs`
- Job（ジョブ）: 一度だけ処理を実行して完了するKubernetes resource。この演習では`s4-log-generator`
- log group（ロググループ）: CloudWatch Logsで関連するログをまとめる入れ物。この演習では`/udemy4/c010/s4/20260725`
- Logs Insights: CloudWatch Logsに保存したログをqueryで検索する機能

## 手順

### 1. Regionとtoolを確認する

CloudShellで次を実行します。

```bash
export AWS_REGION="ap-northeast-1"
export AWS_DEFAULT_REGION="ap-northeast-1"

aws --version
kubectl version --client --output=json
jq --version
aws configure list
df -h "$HOME"
```

**ここまでの成功:** Regionが`ap-northeast-1`で、AWS CLI、kubectl、jqのversionが表示され、容量に空きがあります。容量が不足している場合は次へ進みません。

### 2. 作業directoryと結果保存先を準備する

このREADMEがあるdirectoryへ移動してから、次をまとめて実行します。

```bash
test -f README.md
test -d scripts

export S4_DIR="$(pwd)"
export LEARNER_REPO="$(git -C "$S4_DIR" rev-parse --show-toplevel)"
export EVIDENCE_DIR="$HOME/eks-monitoring-evidence/s4-cloudwatch-logs"
export COMMON_EKS_DIR="$(cd "$S4_DIR/../common-eks" && pwd)"
source "$COMMON_EKS_DIR/scripts/bind-current-identity.sh"
test -f "$CURRENT_STS_IDENTITY_FILE"
test "$(realpath "$(dirname -- "$CURRENT_STS_IDENTITY_FILE")")" = \
  "$(realpath "$PRIVATE_EXECUTION_DIR")"

CLOUDSHELL_PUBLIC_IP="$(curl -fsS https://checkip.amazonaws.com | tr -d '[:space:]')"
export API_PUBLIC_ACCESS_CIDR="${CLOUDSHELL_PUBLIC_IP}/32"

mkdir -p "$EVIDENCE_DIR"
chmod +x "$S4_DIR"/scripts/*.sh
printf 'Section directory: %s\nResult directory: %s\nCloudShell CIDR: %s\n' \
  "$S4_DIR" "$EVIDENCE_DIR" "$API_PUBLIC_ACCESS_CIDR"
```

`EVIDENCE_DIR`はquery結果などの保存先です。Git repositoryの外に置き、account ID、ARN、credentialは保存しません。`bind-current-identity.sh`はcommon EKSのpreflightで作成した非公開の本人確認fileを再検証して再利用します。CloudShellへ再接続した場合も新しいfileを増やさず、既存fileが1件で現在のログイン先と一致するときだけ続行します。fileがない初回は作成し、複数ある場合、内容が不正な場合、現在のログイン先と一致しない場合は停止します。このfileにはaccount IDとARNが含まれるため、Gitへ追加せず、画面、提出物、公開場所へ内容を共有しないでください。credentialも保存・共有しないでください。

**ここまでの成功:** Section directory、result directory、CloudShell CIDRの3行が表示されます。CIDRは現在のCloudShell public IPv4に`/32`を付けた1件だけです。`0.0.0.0/0`は使用しません。

CloudShellへ再接続してIPが変わった場合は、Sectionを実行せず、common EKSの`scripts/recover-cidr.sh`を先に実行します。このscriptは所有対象を確認したうえで`ApiPublicAccessCidr`だけを更新します。

### 3. 作成前の安全確認を行う

```bash
"$S4_DIR/scripts/preflight.sh"
```

**ここまでの成功:** 次の1行が表示されます。

```text
Section 4 preflight passed for exact Region, cluster context, and absent fixed resources.
```

この確認では、現在のdefault CloudShell STS identityの有効性、東京Region、EKS clusterの固定名とARN構造、kubectlの接続先、必要なtagsとoutputsを照合します。また、これから作るNamespaceとlog groupがまだ存在しないことを確認します。条件が1つでも合わない場合、既存resourceを勝手に再利用せず、作成前に停止します。

### 4. EKSでsampleログを6件作る

```bash
"$S4_DIR/scripts/apply-workload.sh"
```

Jobは`INFO` 3件、`WARN` 1件、`ERROR` 2件をJSON形式で出力します。各行には`timestamp`、`namespace`、`pod`、`level`、`message`、`request_id`が入ります。

**ここまでの成功:** 次の形式の1行が表示されます。`<Pod名>`の部分は実行ごとに変わります。

```text
Real EKS Job completed; exact owned Pod <Pod名> emitted six namespace/Pod-validated JSON rows.
```

scriptはPodがこのJobに属する1台だけであることと、6行すべてのNamespaceとPod名が実行中の値に一致することを確認します。

### 5. CloudWatch Logsへ送り、画面で探す（s4-l2）

```bash
"$S4_DIR/scripts/publish-logs.sh"
```

作成される対象は次のとおりです。

- log group: `/udemy4/c010/s4/20260725`
- log stream: `sample-workload`
- retention: 1 day
- tags: `Course=C010`、`Section=s4`、`ManagedBy=udemy4`、`Purpose=training`

**ここまでの成功:** 次の1行が表示されます。

```text
PutLogEvents accepted six events; exact readback and bounded query window were saved locally.
```

scriptは送信が拒否されていないこと、CloudWatchから6件を読み戻せること、元のPodログと内容が一致することを確認します。検索時間は最初と最後のeventの前後2分、最大15分です。

ConsoleでもRegionが東京であることを確認し、CloudWatch → Log groups → `/udemy4/c010/s4/20260725` → `sample-workload`の順に開きます。時間帯、`namespace`、`pod`を見て、6件が同じPodから出ていることを確認してください。

### 6. Logs Insightsで6件とERROR 2件を探す（s4-l3）

```bash
"$S4_DIR/scripts/query-logs.sh"
```

使用するqueryは次の2つです。

- [queries/all-events.logs-insights](queries/all-events.logs-insights): 同じNamespaceとPodの全6件
- [queries/errors.logs-insights](queries/errors.logs-insights): 同じ範囲の`ERROR` 2件

**ここまでの成功:** 次の形式の1行が表示されます。

```text
Bounded Logs Insights queries returned exact 6/2 rows for namespace udemy4-s4-logs and Pod <Pod名>.
```

queryは`Complete`になった場合だけ成功です。raw result、読みやすい形へ変換したresult、`recordsMatched`、`bytesScanned`は`EVIDENCE_DIR`へ保存されます。

ConsoleのLogs Insightsでも同じlog groupと保存された時間帯を選び、query fileの内容を実行して、6件と`ERROR` 2件を確認してください。

## 期待結果

| 確認場所 | 成功の目安 |
| --- | --- |
| EKS Job | 1 Podが完了し、JSONログが6件 |
| ログ内訳 | `INFO` 3件、`WARN` 1件、`ERROR` 2件 |
| CloudWatch Logs | `sample-workload`に同じ6件 |
| all-events query | `Complete`、6件 |
| errors query | `Complete`、`ERROR` 2件 |
| 検索時間 | 0秒より長く、900秒以下 |
| 保存結果 | raw/decoded resultとscan statistics。credentialやaccount identityは含めない |

## Cleanup

学習が終わったら、必ずSectionを先に削除し、次にcommon EKSを削除します。途中でerrorになった場合も、残存確認を飛ばさないでください。

### 1. Section 4のresourceを削除する

```bash
"$S4_DIR/scripts/cleanup-section.sh"
```

**ここまでの成功:** 次の1行が表示されます。

```text
Section cleanup verified: namespace, Job, and fixed CloudWatch log group are absent.
```

scriptは名前とtags/labelsがこの演習の対象と完全に一致するときだけNamespace、Job、log groupを削除します。その後、Namespace、Job、log groupが0件であることをAWS/Kubernetes APIで確認します。AccessDenied、期限切れcredential、network errorを「0件」として扱いません。

### 2. common EKSとcleanup guardを削除する

```bash
export COMMON_EKS_DIR="$(cd "$S4_DIR/../common-eks" && pwd)"
"$COMMON_EKS_DIR/scripts/delete.sh"
```

**ここまでの成功:** 最後に次の1行が表示されます。

```text
Cleanup verified: chargeable residuals are absent and the exact guard was removed last.
```

この成功表示までに、次がすべて0件または不存在になっています。

- common CloudFormation stackとEKS cluster
- この演習のtagsを持つactive EC2、EBS、ENI
- EKS由来のENIとcluster log group
- Section 4のlog group
- cleanup guardのstack、schedule、IAM roles、Lambda、Step Functions state machine

cleanup guardは、通常の削除を忘れた場合に備える期限付きの保護です。通常は自分でSection → commonの順に削除し、課金対象の残存確認が終わった後にguardを最後に削除します。

最終成功表示後、`post-guard-verify.sh`で現在のログイン先を再検証し、cleanup guardの削除後に対象resourceが残っていないことをもう一度確認します。このscriptが成功した場合だけ本人確認fileとその非公開directoryを削除します。

```bash
"$COMMON_EKS_DIR/scripts/post-guard-verify.sh"
unset CURRENT_STS_IDENTITY_FILE PRIVATE_EXECUTION_DIR
```

途中で停止した場合も本人確認fileを先に削除しません。現在のログイン先のままSection cleanup、common cleanup、残存0件の確認、cleanup guardの削除まで完了し、最後に`post-guard-verify.sh`を実行します。再確認に失敗した場合は本人確認fileを保持して停止します。preflightでresource作成前に停止した場合も、固定resourceが存在しないことをcleanup手順と`post-guard-verify.sh`で確認してから破棄します。

必要な結果を手元へdownloadした後、CloudShellの`$HOME` 1 GBを圧迫する不要なcopyは削除できます。

## コストと安全上の注意

このSectionで追加する6件のsample logは小容量ですが、common EKS、EC2、EBS、public IPv4の料金はcleanupが終わるまで続きます。

2026-07-25にAWS Price List APIで確認した東京Regionの標準custom log ingestionはUSD 0.76/GB、Logs Insights scanはUSD 0.0076/GBです。料金は変わるため、実行直前に[CloudWatch pricing](https://aws.amazon.com/cloudwatch/pricing/)と[Amazon EKS pricing](https://aws.amazon.com/eks/pricing/)を確認してください。実請求はtax、discount、Free Tier、billing granularityで異なります。

- 総利用時間は通常4時間、最大6時間以内
- Regionは`ap-northeast-1`だけ
- common resourceのtagは`WorkPackage=c010-common-eks`
- public endpointは現在のCloudShell `/32`だけ。`0.0.0.0/0`は禁止
- 既存resourceや未知のtagを引き継いで使わない

## Fixture fallback

AWSを使えない場合は、fixtureでfilterとschemaだけを確認できます。

```bash
python3 -B "$S4_DIR/analyze.py" --check
python3 -B -m unittest discover -s "$S4_DIR/tests" -p 'test_*.py'
```

この方法で確認できるのはlocalのsyntax/fixture validationだけです。CloudWatch、EKS、IAM、料金、Console上の動作は確認できません。AWSで実行できない場合はここで停止してください。

## Troubleshooting

- Region error: Console selector、CloudShell tab、`AWS_REGION`、`AWS_DEFAULT_REGION`をすべて`ap-northeast-1`へ合わせます。
- kubectl context error: common READMEに従い`aws eks update-kubeconfig --region ap-northeast-1 --name udemy4-c010-common-20260724`を実行します。
- `API_PUBLIC_ACCESS_CIDR` error: CloudShellの現在のpublic IPv4を確認し、common EKSの`scripts/recover-cidr.sh`を実行してからpreflightへ戻ります。
- Pod count/owner error: 既存resourceを流用せず、Section cleanup後にpreflightからやり直します。
- `Expected exactly six schema-valid workload rows`: Pod logが6行か、各行がJSONか、Namespace/Pod名が一致するかを確認します。検査を飛ばしてCloudWatchへ送らないでください。
- queryが`Complete`にならない: statusを保存して停止し、時間帯、log group、Region、permissionを確認します。
- cleanup failure: 表示された残存resourceまたは権限errorを確認します。Section cleanup成功前にcommon cleanupへ進まず、検査をskipしません。
- ownership label mismatch: 追加labelを無視して削除しません。作成元を確認し、判断なしにlabelを削除・上書きしません。
- CloudShell再接続: 同じRegionの`$HOME` fileは残ります。Regionを再設定し、commonの`bind-current-identity.sh`をsourceして既存の本人確認fileを再検証します。新しいprivate directoryは作りません。その後、期限とresource状態を確認し直します。

## 安全設計の補足

各scriptは、次の保護条件をすべて満たす場合だけ処理を続けます。違いがあれば安全側に停止します。

- common stackは固定名、東京Region、5つのownership tags、3つのoutputsを照合する
- EKSはCloudFormationが付けるsystem tagsを含む8つのtags、private endpoint、現在のCloudShell `/32`だけを許可するpublic endpointを照合する
- cleanup用RBACは`s4-log-generator` Jobと`udemy4-s4-logs` Namespaceの`get/delete`だけを許可し、cluster-admin policyを使わない
- Section cleanupは完全なlabels/tagsを確認してから削除し、未知labelがあれば停止する
- 「不存在」はAPIが返す対象固有のnot-found responseだけで判断し、permission/network errorと区別する
- deadline時もSchedulerが直接削除せず、Step FunctionsがSection → common → residual確認 → guardの順序を維持する

これらは固定対象以外の同名resourceやownershipの異なるresourceを変更しないための保護です。error messageを無視して手動削除へ切り替えず、Troubleshootingの該当箇所から確認してください。

## 公式資料

- [AWS CloudShell concepts](https://docs.aws.amazon.com/cloudshell/latest/userguide/working-with-aws-cloudshell.html)
- [AWS CloudShell compute environment](https://docs.aws.amazon.com/cloudshell/latest/userguide/vm-specs.html)
- [Connect kubectl to EKS with kubeconfig](https://docs.aws.amazon.com/eks/latest/userguide/create-kubeconfig.html)
