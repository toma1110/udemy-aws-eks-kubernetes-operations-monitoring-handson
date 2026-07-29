# Section 4: CloudWatch LogsとLogs Insights（AWS CloudShell / Bash）

このハンズオンでは、EKS上のPodが出したログをCloudWatch Logsへ送り、Logs Insightsで必要な行を探します。対象講義は`s4-l2`「CloudWatch LogsでPodログを探す」と`s4-l3`「Logs Insightsの最初のクエリ」です。

すべてのコマンドは、東京Regionを選択して起動した通常のAWS CloudShellで実行します。AWS CloudShellは、ブラウザから利用できるAWS上のコマンド実行環境です。

## 目的

このハンズオンを終えると、次の流れを実行できます。

1. EKSのsample Jobから6件のJSONログを取得する
2. CloudWatch LogsでRegion、log group、時間帯、Pod名を手がかりに6件を見つける
3. Logs Insightsで全6件とERROR 2件へ絞り込む
4. 学習用resourceを安全な順番で削除し、残っていないことを確認する

## 前提条件

開始前に、次の条件をすべて満たしてください。

- AWS Management Consoleへsign inしている
- ConsoleのRegion selectorで東京`ap-northeast-1`を選び、通常のAWS CloudShellを開いている
- [common EKS README](../common-eks/README.md)のpreflight、create、statusを完了し、nodeが1台`Ready`になっている
- AWS CLI `2.12.3`以上、`kubectl`、`jq`、Python 3をCloudShellで利用できる
- `kubectl`のversionがEKS clusterと同じ、または前後1 minor以内である
- CloudShellのRegion別`$HOME`（1 GBの永続領域）に、repositoryと結果を保存できる空きがある
- common EKSを含む総利用時間を通常4時間、最大6時間以内に収められる
- common EKSの作成時に設定したcleanup deadlineを確認できる

このハンズオンでは、次の用語を使います。

- Namespace（名前空間）: Kubernetes resourceを学習単位に分ける入れ物。この演習では`udemy4-s4-logs`
- Job（ジョブ）: 一度だけ処理を実行して完了するKubernetes resource。この演習では`s4-log-generator`
- log group（ロググループ）: CloudWatch Logsで関連するログをまとめる入れ物。この演習では`/udemy4/c010/s4/20260725`
- log stream（ログストリーム）: 1つのlog group内で、同じ送信元のログをまとめる単位。この演習では`sample-workload`
- Logs Insights: CloudWatch Logsに保存したログをqueryで検索する機能
- STS identity: 現在のAWS login先をAWS APIで識別する情報

## 進め方

手順は番号順に実行してください。各scriptは対象のRegion、名前、所有権、接続先を確認し、想定と異なる場合は処理を止めます。

errorを無視したり、検査をskipしたり、同名の既存resourceを流用したりしないでください。停止した場合は[Cleanup](#cleanup)と[Troubleshooting](#troubleshooting)を確認します。

## 手順

### 1. Region、tool、保存容量を確認する

#### 操作

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

#### この操作で確認すること

`aws configure list`で、CloudShellが東京Regionを使用していることを確認します。AWS CLI、`kubectl`、`jq`のversionと、`$HOME`の空き容量も確認します。

容量が不足している場合や、Regionまたはtoolの条件を満たさない場合は次へ進みません。

#### 成功の目安

- Regionが`ap-northeast-1`
- AWS CLIが`2.12.3`以上
- `kubectl`と`jq`のversionが表示される
- `$HOME`にrepositoryと結果を保存できる空きがある

### 2. 作業directoryと結果保存先を準備する

#### 操作

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

#### この操作で確認すること

`S4_DIR`はこのSectionのdirectory、`EVIDENCE_DIR`はquery結果などを置くGit repository外のdirectoryです。`API_PUBLIC_ACCESS_CIDR`には、現在のCloudShell public IPv4を1つのhostだけに限定する`/32`を設定します。

`bind-current-identity.sh`は、現在のdefault CloudShell STS identityが有効であることを確認します。再接続時は、現在のlogin先と一致するfileが1件だけある場合に再利用し、fileが複数ある、壊れている、またはlogin先と一致しない場合は停止します。

`bind-current-identity.sh`はcommon EKSの本人確認fileを再利用します。Section 4用の2個目の本人確認fileは作成しません。

STS identity fileにはAWS account IDとARNが含まれます。内容をterminalへ表示せず、Gitへ追加せず、画面、提出物、公開場所へcopyまたは共有しないでください。credentialも保存または共有しないでください。

#### 成功の目安

次の3行が表示されます。CIDRは現在のCloudShell public IPv4に`/32`を付けた1件だけで、`0.0.0.0/0`ではありません。

```text
Section directory: <Section 4 directory>
Result directory: <Git repository外の結果directory>
CloudShell CIDR: <現在のCloudShell public IPv4>/32
```

CloudShellへ再接続してIPが変わった場合は、Sectionを実行せず、common EKSの`scripts/recover-cidr.sh`を先に実行します。このscriptは所有対象を確認してから`ApiPublicAccessCidr`だけを更新します。

### 3. 作成前の安全確認を行う

#### 操作

```bash
"$S4_DIR/scripts/preflight.sh"
```

#### この操作で確認すること

preflightは、現在のdefault CloudShell STS identity、東京Region、EKS clusterの固定名とARN構造、`kubectl`の接続先、必要なtagsとoutputsを照合します。

これから作成するNamespaceとlog groupが存在しないことも確認します。固定名のresourceがすでに存在する場合は、再利用または更新を行わず停止します。

#### 成功の目安

次の1行が表示されます。

```text
Section 4 preflight passed for exact Region, cluster context, and absent fixed resources.
```

### 4. EKSでsampleログを6件作る

#### 操作

```bash
"$S4_DIR/scripts/apply-workload.sh"
```

#### この操作で確認すること

scriptはNamespaceを作成し、cleanupに必要な限定RBACを設定してからJobを実行します。Jobは`INFO` 3件、`WARN` 1件、`ERROR` 2件をJSON形式で出力します。

各行には`timestamp`、`namespace`、`pod`、`level`、`message`、`request_id`が入ります。scriptはPodがこのJobに属する1台だけであることと、6行すべてのNamespaceとPod名が実行中の値に一致することを確認します。

#### 成功の目安

次の形式の1行が表示されます。`<Pod名>`は実行ごとに変わります。

```text
Real EKS Job completed; exact owned Pod <Pod名> emitted six namespace/Pod-validated JSON rows.
```

### 5. CloudWatch Logsへ送り、画面で探す（s4-l2）

#### 操作

```bash
"$S4_DIR/scripts/publish-logs.sh"
```

作成される対象は次のとおりです。

- log group: `/udemy4/c010/s4/20260725`
- log stream: `sample-workload`
- retention: 1 day
- tags: `Course=C010`、`Section=s4`、`ManagedBy=udemy4`、`Purpose=training`

AWS Management ConsoleでもRegionが東京であることを確認します。CloudWatch → Log groups → `/udemy4/c010/s4/20260725` → `sample-workload`の順に開いてください。

#### この操作で確認すること

scriptは送信が拒否されていないこと、CloudWatchから6件を読み戻せること、元のPodログと内容が一致することを確認します。

検索時間は最初と最後のeventの前後2分で、最大15分です。Consoleでは、時間帯、`namespace`、`pod`を見て、6件が同じPodから出ていることを確認します。

#### 成功の目安

terminalに次の1行が表示され、Consoleの`sample-workload`にも同じ6件が表示されます。

```text
PutLogEvents accepted six events; exact readback and bounded query window were saved locally.
```

### 6. Logs Insightsで6件とERROR 2件を探す（s4-l3）

#### 操作

```bash
"$S4_DIR/scripts/query-logs.sh"
```

使用するqueryは次の2つです。

- [queries/all-events.logs-insights](queries/all-events.logs-insights): 同じNamespaceとPodの全6件
- [queries/errors.logs-insights](queries/errors.logs-insights): 同じ範囲の`ERROR` 2件

CloudWatch Logs Insightsでも同じlog groupと、手順5で保存された時間帯を選びます。それぞれのquery fileの内容を実行してください。

#### この操作で確認すること

scriptはquery statusが`Complete`になった場合だけ結果を受け入れます。全event queryが6件、error queryが2件で、全行のNamespaceとPod名が実行中の値に一致することを確認します。

queryのraw result、読みやすい形へ変換したresult、`recordsMatched`、`bytesScanned`は`EVIDENCE_DIR`へ保存されます。

#### 成功の目安

terminalに次の形式の1行が表示されます。Logs Insightsの画面でも、全6件と`ERROR` 2件を確認できます。

```text
Bounded Logs Insights queries returned exact 6/2 rows for namespace udemy4-s4-logs and Pod <Pod名>.
```

## 期待結果

| 確認場所 | 成功の目安 |
| --- | --- |
| EKS Job | 1 Podが完了し、JSONログが6件 |
| ログ内訳 | `INFO` 3件、`WARN` 1件、`ERROR` 2件 |
| CloudWatch Logs | `sample-workload`に同じ6件 |
| all-events query | `Complete`、6件 |
| errors query | `Complete`、`ERROR` 2件 |
| 検索時間 | 0秒より長く、900秒以下 |
| 保存結果 | raw/decoded resultとscan statisticsを含み、credentialやSTS identityを含まない |

## Cleanup

学習が終わった場合も、途中でerrorになった場合も、次の順番でcleanupします。

1. Section 4のresource
2. common EKS
3. cleanup guard
4. guard削除後の再確認とSTS identity file

必ずSectionを先に削除してください。Section cleanupが成功する前にcommon EKSへ進まず、課金対象の残存確認が終わる前にguardを削除しません。

### 1. Section 4のresourceを削除する

#### 操作

```bash
"$S4_DIR/scripts/cleanup-section.sh"
```

#### この操作で確認すること

scriptは、名前とtagsまたはlabelsがこの演習の対象と完全に一致するときだけNamespace、Job、log groupを削除します。

削除後はNamespace、Job、log groupが不存在であることをKubernetes APIとAWS APIで確認します。AccessDenied、期限切れcredential、network errorを「不存在」として扱いません。

#### 成功の目安

次の1行が表示されます。

```text
Section cleanup verified: namespace, Job, and fixed CloudWatch log group are absent.
```

### 2. common EKSとcleanup guardを削除する

#### 操作

```bash
export COMMON_EKS_DIR="$(cd "$S4_DIR/../common-eks" && pwd)"
"$COMMON_EKS_DIR/scripts/delete.sh"
```

#### この操作で確認すること

common cleanupは、Section 4のresourceが残っていないことを確認してからcommon resourceを削除します。課金対象の残存がないことを確認した後、guardを最後に削除します。

cleanup guardは、通常の削除を忘れた場合に期限付きworkflowを開始する保護です。既定のdeadlineはcommon EKS作成から4時間後で、許可される上限は6時間以内です。通常はdeadlineを待たず、自分でcleanupします。

#### 成功の目安

最後に次の1行が表示されます。

```text
Cleanup verified: chargeable residuals are absent and the exact guard was removed last.
```

この時点で、次がすべて0件または不存在です。

- common CloudFormation stackとEKS cluster
- この演習のtagsを持つactive EC2、EBS、ENI
- EKS由来のENIとcluster log group
- Section 4のlog group
- cleanup guardのstack、schedule、IAM roles、Lambda、Step Functions state machine

### 3. guard削除後にもう一度確認する

#### 操作

```bash
"$COMMON_EKS_DIR/scripts/post-guard-verify.sh"
unset CURRENT_STS_IDENTITY_FILE PRIVATE_EXECUTION_DIR
```

#### この操作で確認すること

`post-guard-verify.sh`は現在のlogin先を再検証し、cleanup guardの削除後に固定対象が残っていないことをもう一度確認します。このscriptが成功した場合だけ本人確認file（STS identity file）とそのprivate directoryを削除します。

途中で停止した場合はSTS identity fileを先に削除しないでください。Section cleanup、common cleanup、残存0件の確認、guardの削除を同じlogin先で完了してから、この手順を再実行します。

preflightでresource作成前に停止した場合も、固定resourceが存在しないことをcleanup手順と`post-guard-verify.sh`で確認してからSTS identity fileを破棄します。

#### 成功の目安

commandが終了code 0で完了し、STS identity fileとその非公開directoryが削除されます。再確認に失敗した場合はfileを保持したまま停止します。

必要な結果を手元へdownloadした後、CloudShellの`$HOME` 1 GBを圧迫する不要なcopyは削除できます。

## コストと安全上の注意

このSectionで追加する6件のsample logは小容量ですが、common EKS、EC2、EBS、public IPv4の料金はcleanupが終わるまで続きます。

2026-07-25にAWS Price List APIで確認した東京Regionの標準custom log ingestionはUSD 0.76/GB、Logs Insights scanはUSD 0.0076/GBです。料金は変わるため、実行直前に[CloudWatch pricing](https://aws.amazon.com/cloudwatch/pricing/)と[Amazon EKS pricing](https://aws.amazon.com/eks/pricing/)を確認してください。実請求はtax、discount、Free Tier、billing granularityで異なります。

安全条件は次のとおりです。

- 総利用時間は通常4時間、最大6時間以内
- Regionは`ap-northeast-1`だけ
- common resourceのtagは`WorkPackage=c010-common-eks`
- public endpointは現在のCloudShell `/32`だけ。`0.0.0.0/0`は禁止
- 固定名、完全なtagsまたはlabels、ARN構造が一致するresourceだけを操作する
- cleanup用RBACは`s4-log-generator` Jobと`udemy4-s4-logs` Namespaceの`get/delete`だけを許可し、cluster-admin policyを使わない
- 既存resource、未知のtagやlabel、所有者が一致しないresourceを引き継いで使わない
- APIのpermission、credential、network errorをresourceの不存在として扱わない

deadline時も、cleanup workflowはSection → common → 残存確認 → guardの順番を維持します。

## AWSを使えない場合の確認

AWSを使えない場合は、fixtureでfilterとschemaだけを確認できます。fixtureは、決められた入力で同じ結果を再現するためのlocal sample dataです。

```bash
python3 -B "$S4_DIR/analyze.py" --check
python3 -B -m unittest discover -s "$S4_DIR/tests" -p 'test_*.py'
```

この方法で確認できるのはlocalのsyntaxとfixture validationだけです。CloudWatch、EKS、IAM、料金、Console上の動作は確認できません。

fixtureが成功してもAWS手順の代わりにはなりません。AWSを実行できない場合は、fixtureの結果だけを確認して終了してください。

## Troubleshooting

### Regionが一致しない

Console selector、CloudShell tab、`AWS_REGION`、`AWS_DEFAULT_REGION`をすべて`ap-northeast-1`へ合わせます。

### kubectl contextが一致しない

common READMEに従い、次を実行します。

```bash
aws eks update-kubeconfig --region ap-northeast-1 --name udemy4-c010-common-20260724
```

### `API_PUBLIC_ACCESS_CIDR`が一致しない

CloudShellの現在のpublic IPv4を確認し、common EKSの`scripts/recover-cidr.sh`を実行してからpreflightへ戻ります。`0.0.0.0/0`や複数CIDRへ広げないでください。

### Pod countまたはownerが一致しない

既存resourceを流用しません。Section cleanupを完了してからpreflightへ戻ります。

### `Expected exactly six schema-valid workload rows`と表示される

Pod logが6行か、各行がJSONか、NamespaceとPod名が一致するかを確認します。検査を飛ばしてCloudWatchへ送らないでください。

### queryが`Complete`にならない

queryのstatusを確認し、時間帯、log group、Region、permissionを見直します。`Failed`、`Cancelled`、`Timeout`、`Unknown`を成功として扱いません。

### cleanupに失敗する

表示された残存resourceまたは権限errorを確認します。Section cleanupが成功する前にcommon cleanupへ進まず、検査をskipしません。

### ownership labelまたはtagが一致しない

追加のlabelやtagを無視して削除しません。作成元を確認し、判断なしにlabelやtagを削除または上書きしないでください。

### CloudShellへ再接続した

同じRegionの`$HOME` fileは次のsessionにも残ります。Regionを再設定し、commonの`bind-current-identity.sh`をsourceして、既存のSTS identity fileを再検証します。新しいprivate directoryは作りません。

現在のIPが変わっている場合は`scripts/recover-cidr.sh`を実行します。cleanup deadlineとresource状態を確認し直し、deadline到達後に別のcleanupを並行実行しないでください。

## 公式資料

- [AWS CloudShell concepts](https://docs.aws.amazon.com/cloudshell/latest/userguide/working-with-aws-cloudshell.html)
- [AWS CloudShell compute environment](https://docs.aws.amazon.com/cloudshell/latest/userguide/vm-specs.html)
- [Connect kubectl to EKS with kubeconfig](https://docs.aws.amazon.com/eks/latest/userguide/create-kubeconfig.html)
