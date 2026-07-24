# EKS PodログをCloudWatch Logs / Logs Insightsで追う

同じrepositoryに含まれる共通EKS基盤を使い、Section 4固有の短命なJobだけを追加します。Jobの実ログを`kubectl logs`で取得し、固定したCloudWatch Logs log groupへAWS CLIで送信した後、AWS ConsoleとLogs Insightsで対象を絞ります。

共通基盤は同じpublic repositoryの`labs/common-eks/`です。Section 4はcluster、VPC、node group、IAMを作り直しません。

## 目的

- `s4-l2`: Region、log group、log stream、短い時間範囲を確認し、Pod由来の実ログをCloudWatch Logsで開く
- `s4-l3`: Logs Insightsで対象log groupと15分以内の時間範囲を選び、namespace、Pod、levelで結果を読む
- 実結果から言える範囲と、fixtureだけで確認した回帰条件を分ける

## 前提条件

1. すでにこのrepositoryをclone済みなら、そのcurrent checkoutを使います。対象directoryがまだない場合だけcloneし、actual Git root、remote、common EKSの基準commitを検証してから2つのlab directoryを固定します。

   ```powershell
   $CURRENT_PUBLIC = (& git rev-parse --show-toplevel 2>$null).Trim()
   if ($LASTEXITCODE -eq 0 -and (Test-Path -LiteralPath (Join-Path $CURRENT_PUBLIC "labs/s4-cloudwatch-logs-insights"))) {
       $env:UDEMY4_PUBLIC = $CURRENT_PUBLIC
   }
   elseif (-not $env:UDEMY4_PUBLIC) {
       $env:UDEMY4_PUBLIC = "C:\work\udemy-aws-eks-kubernetes-operations-monitoring-handson"
   }

   if (-not (Test-Path -LiteralPath $env:UDEMY4_PUBLIC)) {
       git clone https://github.com/toma1110/udemy-aws-eks-kubernetes-operations-monitoring-handson.git $env:UDEMY4_PUBLIC
       if ($LASTEXITCODE -ne 0) { throw "git clone failed" }
   }

   $PUBLIC_WORKTREE = (Resolve-Path -LiteralPath $env:UDEMY4_PUBLIC).Path
   $ACTUAL_PUBLIC_ROOT = (Resolve-Path -LiteralPath ((& git -C $PUBLIC_WORKTREE rev-parse --show-toplevel).Trim())).Path
   if ($LASTEXITCODE -ne 0 -or $ACTUAL_PUBLIC_ROOT -ne $PUBLIC_WORKTREE) {
       throw "UDEMY4_PUBLIC must be the exact public repository root"
   }

   $PUBLIC_ORIGIN = (& git -C $PUBLIC_WORKTREE remote get-url origin).Trim()
   if ($PUBLIC_ORIGIN -notin @(
       "https://github.com/toma1110/udemy-aws-eks-kubernetes-operations-monitoring-handson.git",
       "git@github.com:toma1110/udemy-aws-eks-kubernetes-operations-monitoring-handson.git"
   )) {
       throw "Unexpected public repository origin"
   }

   $EXPECTED_COMMON_COMMIT = "ffead752a1dca7de743674ad057d6e2e457c6953"
   $ACTUAL_COMMON_COMMIT = (& git -C $PUBLIC_WORKTREE log -1 --format=%H -- labs/common-eks).Trim()
   git -C $PUBLIC_WORKTREE diff --quiet $EXPECTED_COMMON_COMMIT -- labs/common-eks
   if ($LASTEXITCODE -ne 0 -or $ACTUAL_COMMON_COMMIT -ne $EXPECTED_COMMON_COMMIT) {
       throw "common EKS files do not match the required commit"
   }

   $S4_LAB_DIR = Join-Path $PUBLIC_WORKTREE "labs/s4-cloudwatch-logs-insights"
   $COMMON_EKS_DIR = Join-Path $PUBLIC_WORKTREE "labs/common-eks"
   $S4_LAB_DIR = (Resolve-Path -LiteralPath $S4_LAB_DIR).Path
   $COMMON_EKS_DIR = (Resolve-Path -LiteralPath $COMMON_EKS_DIR).Path
   ```

2. Section 4は`$S4_LAB_DIR`、common EKSは`$COMMON_EKS_DIR`です。どちらも同じexact public worktree内にあり、repository外へのrelative pathは使用しません。
3. `$COMMON_EKS_DIR\README.md`に従い、exact account、`ap-northeast-1`、固定stack、cleanup deadlineを確認して共通基盤を作成済みであること。
4. AWS CLI v2、kubectl、PowerShell 7、Python 3.11以上。
5. 次の操作を行える権限。権限変更はこの演習に含みません。

   - EKS clusterの参照と既存clusterへのkubectl access
   - namespace / Jobの作成、参照、ログ取得、削除
   - CloudWatch Logsのlog group / stream作成、retention設定、tag、`PutLogEvents`、`StartQuery`、`GetQueryResults`、log group削除

6. 実行前に費用と削除順序を確認します。2026-07-25にAWS Price List APIで確認した東京Regionの標準log classは、custom log ingestionがUSD 0.76/GB、Logs Insights scanがUSD 0.0076/GBです。この演習は数KBのログと15分以内のqueryを2本だけ使うため、Section 4追加分の概算はUSD 0.01未満ですが、最低料金や税、無料枠は仮定しません。共通EKS基盤は別途課金されます。実行直前に[AWS CloudWatch pricing](https://aws.amazon.com/cloudwatch/pricing/)を再確認してください。

## 固定する値

外部scriptはすべて同じ値を再照合します。account IDは公開ファイルや提出物へ保存しません。

```powershell
$env:AWS_ACCOUNT_ID = "<exact-12-digit-account-id>"
$env:EVIDENCE_DIR = "C:\udemy4-evidence\s4-cloudwatch-logs"
New-Item -ItemType Directory -Force $env:EVIDENCE_DIR | Out-Null
$env:EVIDENCE_DIR = (Resolve-Path -LiteralPath $env:EVIDENCE_DIR).Path
```

`EVIDENCE_DIR`はabsolute pathで、`$PUBLIC_WORKTREE`の内側には置けません。各external scriptはpublic worktreeを再解決し、evidence pathがその配下、または別のGit worktree内なら実行を拒否します。

| 項目 | 固定値 |
| --- | --- |
| Region | `ap-northeast-1` |
| common cluster | `udemy4-c010-common-20260724` |
| namespace | `udemy4-s4-logs` |
| Job | `s4-log-generator` |
| log group | `/udemy4/c010/s4/20260725` |
| log stream | `sample-workload` |
| retention | 1日 |
| 最大利用 | common EKS作成時に設定したcleanup deadlineまで、6時間以内 |

同名namespace、Job、log group、log streamが既に存在する場合は停止し、既存resourceを採用・更新しません。

## 手順

### 1. common EKSを再確認する

それぞれのactual directoryにあるscriptをabsolute pathで実行します。

```powershell
& (Join-Path $COMMON_EKS_DIR "scripts/status.ps1")
& (Join-Path $S4_LAB_DIR "scripts/preflight.ps1")
```

期待結果:

- STS accountが`AWS_ACCOUNT_ID`と一致する
- Regionは`ap-northeast-1`
- kubectl contextがexact cluster ARNに一致する
- common stack / clusterのownership bindingが一致する
- Section 4のnamespace、Job、log groupがまだ存在しない

### 2. sample workloadを実行する

```powershell
& (Join-Path $S4_LAB_DIR "scripts/apply-workload.ps1")
. (Join-Path $S4_LAB_DIR "scripts/common.ps1")
$ACTUAL_POD = Get-ExactJobPodName
```

期待結果:

- Job `s4-log-generator`が`Complete`
- `kubectl logs job/s4-log-generator -n udemy4-s4-logs`が6行のJSONを返す
- scriptはlabel selectorで得たPodがexactly 1件で、runtime JobのUIDを持つcontroller owner referenceがexactly 1件であることを検証し、そのactual Pod名を`$ACTUAL_POD`へ保存する
- 6行すべてに`timestamp`、`namespace`、`pod`、`level`、`message`、`request_id`があり、`namespace`は`udemy4-s4-logs`、`pod`はexact runtime `$ACTUAL_POD`と一致する。不一致行が1件でもあれば停止する
- levelは`INFO` 3件、`WARN` 1件、`ERROR` 2件

実際に手順を実行した場合だけ、ここで表示された出力を実clusterのCLI結果として扱います。結果が違う場合は先へ進まず、Pod events、image pull、Job statusを確認します。AWSとkubectlを実行するまでは、上記を実結果として扱いません。

### 3. 実ログをCloudWatch Logsへ送る

```powershell
& (Join-Path $S4_LAB_DIR "scripts/publish-logs.ps1")
```

期待結果:

- fixed log groupとstreamが作成され、retentionが1日になる
- 6件の実Jobログが`PutLogEvents`でacceptedになる
- 実行時刻を含む15分以内のquery範囲が`query-window.json`へ保存される

### 4. CloudWatch Logs画面で確認する（s4-l2）

1. AWS Console右上のRegionを東京 `ap-northeast-1`にします。
2. CloudWatch → Logs → Log groupsを開きます。
3. `/udemy4/c010/s4/20260725`を選び、`sample-workload`を開きます。
4. `query-window.json`のstart/endを含む短い時間範囲へ合わせます。
5. JSON eventを1件開き、namespace、Pod、level、message、request IDを確認します。

期待結果: CLIで送った6件が同じlog streamに表示されます。Console captureを教材へ使う場合はaccount ID、email、credential、不要なresource識別子をcrop/maskし、生成UIへ置き換えません。

### 5. Logs Insights queryを実行する（s4-l3）

```powershell
& (Join-Path $S4_LAB_DIR "scripts/query-logs.ps1")
```

scriptはexactly 1件のJob-owned Podを再解決し、`query-window.json`の15分以内の範囲とfixed log groupだけを使って`queries/all-events.logs-insights`と`queries/errors.logs-insights`を順に実行します。両queryは`namespace`をprojectし、actual namespace `udemy4-s4-logs`と、Jobが生成するactual Pod名に一致する`pod like /^s4-log-generator-/`で絞ります。AWS結果をfield/value行からdecodeし、全行の`namespace`と`pod`がruntime値に一致することを検証します。

期待結果:

- query statusが`Complete`
- all-events queryはexactly 6件を時刻昇順で返す。6件以外ならscriptは失敗する
- errors queryは`level = "ERROR"`をexactly 2件返す。2件以外または非ERROR行があればscriptは失敗する
- 返された各eventの`namespace`は`udemy4-s4-logs`、`pod`はactual `$ACTUAL_POD`
- `statistics.recordsMatched`と`statistics.bytesScanned`を含む実サービス結果がlocal evidenceへ保存される

ConsoleでもCloudWatch → Logs Insightsを開き、同じlog groupとcustom time rangeを選んでqueryを貼り付けます。query結果は初動の観測であり、同じrequest IDや近い時刻だけから原因を確定しません。

## Cleanup

Section固有resourceを先に削除し、残存がないことを確認してから共通基盤を削除します。

```powershell
& (Join-Path $S4_LAB_DIR "scripts/cleanup-section.ps1")
& (Join-Path $S4_LAB_DIR "scripts/verify-cleanup.ps1")
& (Join-Path $COMMON_EKS_DIR "scripts/delete.ps1")
```

`verify-cleanup.ps1`はnamespace、Job、fixed log groupをそれぞれ実APIで確認します。`ResourceNotFound`だけを不在として扱い、AccessDenied、credential、network、throttlingはcleanup成功にしません。common cleanupはCloudFormation、EKS、EC2、EBS、ENI、CloudWatch、cleanup guardの残存確認を行います。

## Fixture fallback

AWS account、exact approval、権限、共通clusterがない場合はAWS操作を行いません。`fixtures/`と`analyze.py`はqueryの考え方を回帰確認するfallbackであり、CloudWatch Logsへの配信、Console、Logs Insights service、IAM、billing、実EKS挙動を証明しません。

```powershell
python -B (Join-Path $S4_LAB_DIR "analyze.py") --check
python -B -m unittest discover -s (Join-Path $S4_LAB_DIR "tests") -v
```

## Troubleshooting

- `STS account does not equal AWS_ACCOUNT_ID`: credentialを変更せず、対象accountをCourse ownerの承認へ結合してから再実行します。
- `kubectl context must equal`: common EKSの`status.ps1`からやり直します。substring一致や別clusterは許可しません。
- `fixed resource already exists`: 削除・採用・更新せず停止します。ownershipを確認できない同名resourceには触れません。
- Jobが`Complete`にならない: `kubectl describe job`と`kubectl get events -n udemy4-s4-logs --sort-by=.lastTimestamp`を確認します。
- Consoleにログがない: Region、log group、stream、custom time rangeを順に確認し、CLIの`describe-log-streams`と`get-log-events`を使います。
- queryが0件: `query-window.json`、選択log group、JSON field discovery、query statusを確認します。時間範囲を無制限に広げません。
- cleanupが失敗: common EKSを先に消さず、Section 4のnamespaceとlog groupが不在になるまでexact errorを解消します。

## 公式資料

- [Send logs to a log group](https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/Working-with-log-groups-and-streams.html)
- [CloudWatch Logs Insights query syntax](https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/CWL_QuerySyntax.html)
- [SOURCE command / start-query example](https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/CWL_QuerySyntax-Source.html)
- [CloudWatch pricing](https://aws.amazon.com/cloudwatch/pricing/)
