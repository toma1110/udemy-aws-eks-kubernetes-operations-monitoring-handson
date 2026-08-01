# Section 7: CloudWatch Observability の欠落を切り分ける

このハンズオンでは、CloudWatch のメトリクスやログが見えないときに、Amazon EKS add-on、Agent Pod、DaemonSet、Node、設定、IAM、Region、CloudWatch の順で事実を確認します。AWS Management Console で東京リージョンを選び、AWS CloudShell の Bash で実行します。

[Section 7 のハンズオンリソースを開く](https://github.com/toma1110/udemy-aws-eks-kubernetes-operations-monitoring-handson/tree/main/labs/s7-observability-first-response)

## 学習目標

1. Agent Pod の `Pending`、`ImagePullBackOff`、`CrashLoopBackOff` を最初の手掛かりとして確認する。
2. メトリクス欠落を add-on、DaemonSet、taint、network の兆候、IAM、enhanced observability の観点へ分ける。
3. ログ欠落を Region、log group、Agent 設定、IAM の観点へ分ける。
4. `kubectl` と AWS CLI の結果から次の安全な確認先を選ぶ。

この演習は読み取りだけです。add-on、IAM policy、Pod Identity association、Kubernetes resource、log group を作成、更新、削除しません。

## 1. CloudShell を開く

AWS Management Console で東京リージョン `ap-northeast-1` を選び、CloudShell を開きます。

```bash
export AWS_REGION="ap-northeast-1"
export AWS_DEFAULT_REGION="ap-northeast-1"
aws --version
kubectl version --client --output=json
printf 'HOME=%s\n' "$HOME"
df -h "$HOME"
```

期待結果:

- AWS CLI と kubectl の version が表示される。
- CloudShell の `$HOME` に空き容量がある。永続領域は Region ごとに 1 GB です。

AWS Management Console 上の account 表示が利用予定と異なる場合は停止してください。後の準備 script は現在の STS identity を Git 管理外の非公開ファイルへ保存し、account ID や ARN を terminal へ表示しません。

## 2. 教材を準備する

```bash
export HANDSON_REPO="$HOME/udemy-aws-eks-kubernetes-operations-monitoring-handson"
export HANDSON_URL="https://github.com/toma1110/udemy-aws-eks-kubernetes-operations-monitoring-handson.git"

if [[ -e "$HANDSON_REPO" ]]; then
  [[ -d "$HANDSON_REPO/.git" ]] || {
    echo "同名 directory が Git repository ではありません。" >&2
    exit 1
  }
  [[ "$(git -C "$HANDSON_REPO" remote get-url origin)" == "$HANDSON_URL" ]] || {
    echo "既存 repository の origin が教材 URL と異なります。" >&2
    exit 1
  }
  [[ -z "$(git -C "$HANDSON_REPO" status --porcelain)" ]] || {
    echo "既存 repository に変更中の file があります。" >&2
    exit 1
  }
  git -C "$HANDSON_REPO" pull --ff-only
else
  git clone "$HANDSON_URL" "$HANDSON_REPO"
fi

cd "$HANDSON_REPO/labs/s7-observability-first-response"
export S7_DIR="$(pwd)"
export COMMON_EKS_DIR="$HANDSON_REPO/labs/common-eks"
chmod +x "$S7_DIR"/scripts/*.sh
```

## 3. 共通 EKS 環境を確認する

この Section は、[共通 EKS 環境](../common-eks/README.md)を変更せず再利用します。環境がない場合だけ共通 README に従って作成してください。共通環境の固定 stack、cluster、tag、最大 6 時間、cleanup guard、残存確認の契約を変更しません。

CloudWatch Observability add-on がないことも有効な診断結果です。この Section のために add-on や権限を追加せず、「add-on 不在」を最初の原因候補として記録します。

## 4. 機密情報を含む観察記録の保存先を準備する

今回の実行を区別する名前を作り、共通環境と同じ現在の STS identity を使う Git 管理外の非公開領域を準備します。

```bash
export S7_RUN_ID="$(date -u '+%Y%m%dT%H%M%SZ')-$(od -An -N4 -tx1 /dev/urandom | tr -d ' \n')"
export API_PUBLIC_ACCESS_CIDR="$(curl -fsS https://checkip.amazonaws.com | tr -d '[:space:]')/32"
source "$S7_DIR/scripts/prepare-private-run.sh"
"$S7_DIR/scripts/preflight.sh"
```

期待結果は、account ID や ARN を含まない `Section 7 の事前確認が完了しました` です。preflight と capture は、最初の AWS read として現在の default STS identity を取得し、共通環境が保持する唯一の非公開 identity 記録と完全一致することを毎回確認します。今回用の保存先がすでにある場合、Region 不一致、common stack/tag/context 不一致、現在 identity 不一致では停止します。

## 5. add-on と Agent Pod を確認する

```bash
"$S7_DIR/scripts/capture-observations.sh"
```

script は次を Git 管理外の非公開ファイルへ保存します。

- `amazon-cloudwatch-observability` add-on の status、health issue、設定
- `amazon-cloudwatch` namespace の Pod、DaemonSet、ServiceAccount、ConfigMap、event
- Node の Ready condition と taint
- Container Insights の metric namespace と cluster prefix の log group

取得 error の本文、ConfigMap の値、Agent log、AWS principal は Git 管理外の非公開ファイルだけへ保存し、terminal へ表示しません。機密情報を含む可能性があるため、Git へ追加したり共有したりしないでください。add-on や namespace が存在しない場合も、欠落として判定できる status を保存します。read permission が拒否された場合は「存在しない」と読み替えません。

## 6. メトリクス欠落を診断する

```bash
python3 "$S7_DIR/analyze.py" \
  --input "$S7_EVIDENCE_DIR/normalized-observations.json" \
  --output "$S7_EVIDENCE_DIR/summary.json"
jq . "$S7_EVIDENCE_DIR/summary.json"
```

次の順で確認します。

1. `addon.observed` が false なら、read 拒否か add-on 不在かを `reason` で分ける。
2. add-on が `ACTIVE` でなければ、`health_issue_codes` と Agent Pod の状態を確認する。Pod phase が `Running` でも、container の `waiting.reason` が `CrashLoopBackOff` や `ImagePullBackOff` なら event と current / previous log を確認する。
3. DaemonSet の `desired` と `ready` が一致しなければ、Node taint、scheduling event、resource 不足を確認する。
4. `agent_logs.observed` が true の場合だけ、Agent log の `AccessDenied` を IAM / Pod Identity、timeout や DNS error を network 経路の兆候として扱う。false の場合は `reason` に従って取得不能を先に解消する。
5. add-on、Pod、DaemonSet が正常でも metric が見えなければ、enhanced observability の設定と CloudWatch の時間範囲を確認する。

観察できなかった項目を正常または異常と断定しないでください。

## 7. ログ欠落を診断する

機密情報を除いた要約だけを確認するため、次を実行します。

```bash
jq '{logs, agent_logs, configuration, addon_configuration_values_present: .addon.configuration_values_present}' \
  "$S7_EVIDENCE_DIR/summary.json"
```

`configuration` の意味:

- `agent_log_pipeline_config_present`: Agent ConfigMap に log pipeline 候補の非空設定があるかを示す。存在だけでは有効化や配送成功を証明しない。
- `container_logs_override`: add-on の明示 override が `enabled` / `disabled` / `not-specified` / `not-observed` のどれかを示す。
- `otel_container_insights_override`: トップレベルの `otelContainerInsights.enabled` 設定を同じ4状態で示す。`not-specified`の場合、OTel Container InsightsはAWS公式仕様上defaultでdisabledです。
- `classic_container_insights_override`: トップレベルのClassic設定 `containerInsights.enabled`を同じ4状態で示す。未指定時の実効状態はadd-on version/defaultに依存するため断定しません。
- `legacy_enhanced_observability_override`: 旧来の階層にある `agent.config.logs.metrics_collected.kubernetes.enhanced_container_insights` 設定を同じ4状態で示す。旧設定との互換確認用であり、2つのトップレベル設定の代用にはしません。
- `effective_log_collection`: 明示 override がある場合だけ `explicitly-enabled-by-addon-override` または `explicitly-disabled` とし、default依存なら `not-determined` とする。
- `approach_interpretation.configured_mode_signal`: 2つのトップレベル設定と旧来の階層設定の組み合わせから `otel-only-configured`、`dual-publish-configured`、`classic-only-configured`、`legacy-classic-configured`、`default-dependent`などを示す。これは設定の分類であり、実際にデータが配送されている証明ではありません。
- `addon_configuration_values_present`: add-on に設定文字列がある事実だけを示し、enhanced observability や log collection が有効であることは示さない。

`agent_logs` はAgent log本文を読めたかを示します。`observed: false` の場合、`reason` は `read-denied`、`no-target`、`unavailable` のいずれかです。この状態では `agent_signals` のfalseを「AccessDenied、network error、configuration errorがなかった」という否定証拠に使いません。権限、対象Pod、または一時的な取得失敗を先に確認してください。

OTelとClassicのdual publishはadd-on version `v6.2.0`以降の機能です。`dual-publish-configured`が表示されても、summaryの`addon.version`、Agent状態、metric/logの実データを別々に確認します。OTel-only、dual publish、Classic/legacyのどの設定でも、この演習はlive modeやデータ鮮度を設定値だけから断定しません。

続いて summary の `logs` を確認します。

- `region` が `ap-northeast-1` か。
- `/aws/containerinsights/udemy4-c010-common-20260724/` prefix の log group が観察できたか。
- Agent log pipeline 候補の存在、add-on の明示 override、または default 依存のどこまで確認できたか。
- Agent log に `AccessDenied`、endpoint、DNS、timeout の兆候があるか。
- Agent logを観察できなかった場合は、その `reason` とsummaryの明示的な次の確認先。

log group がない場合、Region、add-on、Agent、設定、権限のどこまで確認できたかを記録します。log group があるだけでは、新しい log event が届いていることを証明しません。

## 8. 診断結果から次の確認先を選ぶ

| 観察した事実 | 最初の確認先 | 安全な次の行動 |
| --- | --- | --- |
| add-on が不在 | EKS add-on 構成 | cluster 管理者へ必要性と採用する identity 方式を確認 |
| Agent Pod が `Pending` | scheduling | Node capacity、taint、DaemonSet toleration、event を確認 |
| `ImagePullBackOff` | image / ECR 到達性 | Pod event と Node から ECR への経路を確認 |
| `CrashLoopBackOff` | Agent 設定 | current / previous log と ConfigMap を確認 |
| Agent logが`read-denied` | log read権限 | 権限を追加せず、cluster管理者へ必要なread権限を確認 |
| Agent logが`no-target` | Agent Pod選択 | labelとAgent Podの存在を確認 |
| Agent logが`unavailable` | log取得経路 | Git 管理外のエラー記録を確認し、同じ対象でcaptureを再試行 |
| Agent log に `AccessDenied` | IAM / Pod Identity | denied action と利用主体を管理者へ共有 |
| timeout / DNS error | network | security group、DNS、CloudWatch endpoint / public egress を確認 |
| metric だけ欠落 | enhanced observability / 時間範囲 | add-on 設定と CloudWatch 表示条件を確認 |
| log だけ欠落 | Region / log pipeline | log group prefix、Agent log 設定、権限を確認 |

この演習中に権限や add-on を追加して結果を合わせません。変更が必要なら、管理者が影響、費用、rollback を別途確認します。

## 9. Cleanup

Section 7 は AWS resource や Kubernetes resource を作りません。最初に、今回の観察記録だけを削除し、空になった `s7-observations` directoryも削除します。別の観察記録や不明なfileがある場合は何も削除せず停止します。cleanup後の共通の非公開保存先には `current-sts-identity.json` だけを残します。

```bash
"$S7_DIR/scripts/cleanup-local-evidence.sh"
```

共通 EKS 環境をこの後使わない場合は、他 Section の cleanup が終わっていることを確認してから削除します。

```bash
"$COMMON_EKS_DIR/scripts/delete.sh"
"$COMMON_EKS_DIR/scripts/post-guard-verify.sh"
unset CURRENT_STS_IDENTITY_FILE PRIVATE_EXECUTION_DIR
```

共通 cleanup は Section → common → guard の順です。CloudFormation、EKS、EC2、EBS、ENI、CloudWatch の残存確認がすべて成功するまで identity file を手作業で消しません。

## 費用

Section 7 の read-only 診断 command は新しい resource を作りません。主な費用は、既に稼働している共通 EKS 環境と、既に有効な CloudWatch telemetry の利用量です。共通環境では 6 時間の EKS、EC2、EBS、public IPv4 subtotal を約 USD 0.97 と見積もっています。2026-07-31 に公式料金を再確認した時点で、標準 support の EKS control plane は USD 0.10/cluster-hour、Container Insights with enhanced observability は observation 数に応じる段階料金で、container log の取り込みと保存は別料金です。

実請求は Region、Kubernetes support tier、利用時間、metric/log/observation 量、税、割引で変わります。開始直前に [Amazon EKS pricing](https://aws.amazon.com/eks/pricing/)、[Amazon CloudWatch pricing](https://aws.amazon.com/cloudwatch/pricing/)、[Amazon EC2 On-Demand pricing](https://aws.amazon.com/ec2/pricing/on-demand/)を確認し、共通環境は最大 6 時間以内に削除してください。

## Troubleshooting

- `Section 7 の事前確認が完了しました` にならない: 最初の error を Git 管理外の非公開ログで確認し、capture へ進みません。
- `addon-not-found`: 欠落原因の一つです。この演習中に add-on を作らず、cluster 管理者へ共有します。
- `read-denied`: 不在とは判定しません。必要な read permission を管理者へ確認します。
- `Pending`: Pod event、Node taint、DaemonSet toleration、resource request を確認します。
- `ImagePullBackOff`: Pod event の image 名と ECR 到達性を確認します。
- `CrashLoopBackOff`: current log に加えて `--previous` の log を確認します。
- log group がない: Region と prefix を再確認し、Agent / add-on 不在と IAM / network を分けます。
- metric がない: CloudWatch の時間範囲、add-on 設定、enhanced observability、Agent 状態を確認します。
- 観察記録の保存先がすでにある: 古い記録を上書きせず、新しい `S7_RUN_ID` で最初から実行します。
- cleanup 後の確認が停止する: 共通 identity を消さず、表示された exact residual を解消します。

## 公式資料

- [Troubleshooting Container Insights on Amazon EKS](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/container-insights-eks-troubleshooting.html)
- [Install the CloudWatch Observability EKS add-on](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/install-CloudWatch-Observability-EKS-addon.html)
- [Container Insights with enhanced observability metrics](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/Container-Insights-metrics-enhanced-EKS.html)
- [OTel Container Insights and dual publishing](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/container-insights-eks-otel.html)
- [AWS CloudShell Region and storage](https://docs.aws.amazon.com/cloudshell/latest/userguide/working-with-aws-cloudshell.html)

## 固定サンプルで動作を確認する

AWSへ接続せず、同梱した固定サンプルに対するanalyzerと安全契約を確認できます。

```bash
python3 -m unittest discover -s tests -v
```

## ライセンス

この教材はrepository rootの[MIT License](../../LICENSE)に従います。
