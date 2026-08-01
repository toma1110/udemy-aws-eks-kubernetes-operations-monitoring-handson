# Section 8: 初動対応Runbookとコスト・削除確認

このハンズオンでは、EKS障害の初動確認をRunbookへ整理し、学習用リソースの料金とcleanup境界を確認します。AWS Management Consoleで東京リージョン `ap-northeast-1` を選び、通常のAWS CloudShellのBashで実行します。

このSectionはAWSリソースを作成、更新、削除しません。前のSectionで共通EKS環境を使っている場合も、ここでは読み取り専用で状態を確認し、削除は共通環境の所有権検査付き手順へ戻します。

## 学習目標

1. 症状、影響、時刻、Pod、Node、ログ、メトリクス、イベント、権限を一つのRunbookへまとめる。
2. 観察した事実と推測を分け、次の確認とエスカレーション条件を決める。
3. EKSと周辺リソースの料金発生源、所有者、削除順序を確認する。
4. 「見つかったリソース」と「削除してよいリソース」を区別し、残存確認まで含めたcleanupを説明する。

## 前提条件

- AWS Management Console、CloudWatch Logs / Metrics、IAMの基本用語を理解している。
- Bash、AWS CLI、`kubectl`、`jq`、Python 3を使える。
- live環境を観察する場合は、読み取り対象のEKS clusterとCloudWatchへアクセスできる。
- 共通EKS環境を使う場合は、`../common-eks`の作成時と同じAWS identity、固定Region、固定stack / cluster、所有権tagを再検証できる。

## 1. CloudShellを確認する

AWS Management Consoleで東京リージョン `ap-northeast-1` を選び、VPC environmentではない通常のCloudShellを開きます。

```bash
export AWS_REGION="ap-northeast-1"
export AWS_DEFAULT_REGION="ap-northeast-1"

aws --version
kubectl version --client --output=json
jq --version
python3 --version
printf 'HOME=%s\n' "$HOME"
df -h "$HOME"
```

期待結果:

- AWS CLI、kubectl、jq、Python 3のversionが表示される。
- `$HOME`に空き容量がある。通常のCloudShellでは、Regionごとに1 GBの永続領域を利用できます。

Consoleに表示されたAWS accountが利用予定と異なる場合は停止します。account ID、ARN、credentialをRunbook、terminalの共有記録、GitHubへ貼り付けません。

## 2. 教材を準備する

```bash
export HANDSON_REPO="$HOME/udemy-aws-eks-kubernetes-operations-monitoring-handson"
export HANDSON_URL="https://github.com/toma1110/udemy-aws-eks-kubernetes-operations-monitoring-handson.git"

if [[ -e "$HANDSON_REPO" ]]; then
  [[ -d "$HANDSON_REPO/.git" ]] || {
    echo "同名directoryがGit repositoryではありません。" >&2
    exit 1
  }
  [[ "$(git -C "$HANDSON_REPO" remote get-url origin)" == "$HANDSON_URL" ]] || {
    echo "既存repositoryのoriginが教材URLと異なります。" >&2
    exit 1
  }
  [[ -z "$(git -C "$HANDSON_REPO" status --porcelain)" ]] || {
    echo "既存repositoryに変更中のfileがあります。" >&2
    exit 1
  }
  git -C "$HANDSON_REPO" pull --ff-only
else
  git clone "$HANDSON_URL" "$HANDSON_REPO"
fi

cd "$HANDSON_REPO/labs/s8-operations-runbook"
export S8_DIR="$(pwd)"
```

## 3. fixtureでRunbookを検証する

Runbookは、観察した事実、仮説、次の安全な確認を分けて記録します。まず、完成例をlocal fixtureで検証します。

```bash
python3 "$S8_DIR/validate_operations_pack.py" runbook \
  "$S8_DIR/fixtures/completed-runbook.md"
```

期待結果:

```text
PASS: runbook contract is complete
```

次に、[Runbook template](templates/first-response-runbook.md)をprivate作業directoryへコピーします。

```bash
export S8_PRIVATE_DIR="$HOME/eks-monitoring-private/c010-s8"
install -d -m 700 "$S8_PRIVATE_DIR"
install -m 600 "$S8_DIR/templates/first-response-runbook.md" \
  "$S8_PRIVATE_DIR/first-response-runbook.md"
```

Runbookにはaccount ID、ARN、credential、個人情報、未加工のlog全文を保存しません。必要な識別子は、共有可能なcluster名、namespace、workload名、時間帯に絞ります。

## 4. live環境を読み取り専用で確認する

live環境がない場合は、この手順を飛ばしてfixtureだけで進めます。共通EKS環境を使う場合は、先に同じcheckoutにある共通環境の唯一のidentity bindingを再利用します。

```bash
export COMMON_EKS_DIR="$HANDSON_REPO/labs/common-eks"
source "$COMMON_EKS_DIR/scripts/bind-current-identity.sh"

CLOUDSHELL_PUBLIC_IP="$(curl -fsS https://checkip.amazonaws.com | tr -d '[:space:]')"
export API_PUBLIC_ACCESS_CIDR="${CLOUDSHELL_PUBLIC_IP}/32"
python3 "$S8_DIR/scripts/validate_common_status_redacted.py"
```

期待結果は `Common EKS status validation passed.` だけです。wrapperはcommon `status.sh`の成功stdoutをmode 600のprivate temporary fileへ隔離し、終了時に削除します。失敗時はcommon `status.sh`のstderrをそのまま表示しますが、途中まで取得したJSON stdoutはterminalへ戻しません。

この検証がRegion、固定stack / cluster、所有権tag、kubectl context、現在のSTS identityを確認できた場合だけ、次の読み取りコマンドを実行します。

```bash
kubectl get pods -A -o wide
kubectl get nodes
kubectl get events -A --sort-by=.lastTimestamp
kubectl get svc -A
kubectl get ingress -A

aws eks describe-cluster \
  --region "$AWS_REGION" \
  --name "udemy4-c010-common-20260724" \
  --query 'cluster.{Name:name,Status:status,Version:version}' \
  --output table
```

期待結果:

- Pod、Node、eventを同じ時刻帯で比較できる。
- ServiceとIngressの外部公開有無を確認できる。
- 固定clusterの名前、状態、Kubernetes versionだけが表示され、account IDやARNは表示されない。

`Forbidden`、`Unauthorized`、`AccessDenied`、接続失敗が出た場合は、演習のために権限を追加しません。Runbookへerrorの分類と次の確認先だけを記録します。

## 5. 初動対応Runbookを完成する

private copyを編集し、次を埋めます。

1. 症状、開始時刻、影響範囲を記録する。
2. Pod、Node、event、log / metric、権限の観察事実を記録する。
3. 事実からまだ分からない点を分ける。
4. 次の読み取り確認と、変更を伴う対応の承認者を決める。
5. エスカレーション条件を明記する。

```bash
python3 "$S8_DIR/validate_operations_pack.py" runbook \
  "$S8_PRIVATE_DIR/first-response-runbook.md"
```

確認用スクリプトの成功は、Runbookの必須項目が埋まったことを示します。原因が正しいことや、障害が解消したことまでは証明しません。

## 6. コストとcleanup inventoryを確認する

まず、決定論的なsample inventoryを検証します。

```bash
python3 "$S8_DIR/validate_operations_pack.py" inventory \
  "$S8_DIR/fixtures/sample-cost-cleanup-inventory.json"
```

期待結果:

```text
PASS: cost and cleanup inventory is safe
```

sampleは、EKS control plane、EC2 worker、EBS、public IPv4、CloudWatch Logsなどが別々に課金され得ることと、検出だけでは削除承認にならないことを示します。live環境では、次の読み取り結果と請求画面を使い、自分が作成したexact resource、Region、所有権tag、利用時間をinventoryへ記録します。

```bash
aws eks list-clusters --region "$AWS_REGION" --output table
aws cloudformation list-stacks \
  --region "$AWS_REGION" \
  --stack-status-filter CREATE_COMPLETE UPDATE_COMPLETE UPDATE_ROLLBACK_COMPLETE \
  --query 'StackSummaries[].[StackName,StackStatus]' \
  --output table
aws logs describe-log-groups \
  --region "$AWS_REGION" \
  --log-group-name-prefix "/aws/" \
  --query 'logGroups[].[logGroupName,storedBytes]' \
  --output table
```

EKSの標準support cluster feeは料金ページで時間単価を確認し、EC2、EBS、public IPv4、CloudWatch、data transferは別料金として見積もります。金額はRegion、利用時間、Kubernetes support tier、log量、割引、税で変わるため、実行直前のAWS公式料金とCost Explorer / Billingで確認してください。

## 7. cleanupの判断と順序

このSectionのコマンドだけを実行した場合、新しいAWSまたはKubernetes resourceはないため、Section固有のAWS cleanupはありません。private Runbookだけを削除できます。

```bash
rm -f -- "$S8_PRIVATE_DIR/first-response-runbook.md"
rmdir -- "$S8_PRIVATE_DIR" 2>/dev/null || true
```

共通EKS環境を削除する場合は、任意のlist結果から名前を選んで削除してはいけません。次の順序を守ります。

1. 各SectionのREADMEに従い、Section固有のnamespace、Job、log groupをcleanupする。
2. `kubectl get svc -A`と`kubectl get ingress -A`で外部Load Balancerを持つ対象を確認する。
3. 共通環境の`delete.sh`で、固定Region、stack / cluster、所有権tag、作成時と同じSTS identity、Section残存0を再照合して削除する。
4. `post-guard-verify.sh`でEKS、EC2、EBS、ENI、CloudWatchとcleanup guardの残存0を再確認する。
5. すべてpassした後だけ、private identity fileを削除する。

```bash
"$COMMON_EKS_DIR/scripts/delete.sh"
"$COMMON_EKS_DIR/scripts/post-guard-verify.sh"
unset CURRENT_STS_IDENTITY_FILE PRIVATE_EXECUTION_DIR
```

対象、所有権、費用、削除順序、復旧方法のいずれかが不明なら削除せず、環境の作成者またはAWS管理者へエスカレーションします。

## Troubleshooting

- `runbook contract is incomplete`: validatorが示した見出しまたは未置換placeholderを直します。
- `inventory ... unsafe`: Region、料金確認時刻、resource所有者、削除承認、残存確認のいずれかが不明です。不明なまま削除しません。
- common status validationが停止する: stderrに表示された診断を確認します。新しいidentity fileを作らず、同じRegionで`bind-current-identity.sh`をsourceし直します。複数候補やidentity不一致は管理者へ共有します。private temporary stdoutはterminalへ貼り付けません。
- `kubectl`接続失敗: current context、CloudShellのpublic IPv4、EKS endpoint CIDRを確認し、必要ならcommonの`recover-cidr.sh`だけを使います。
- `AccessDenied`: この演習のためにIAM policyを追加せず、denied actionと必要な読み取り範囲を管理者へ共有します。
- Load Balancerが残る: clusterを先に削除せず、該当Service / Ingressの所有者を確認します。
- 削除後の残存確認が失敗する: identity fileやcleanup guardを先に消さず、表示されたexact residualを調査します。

## 公式資料

- [AWS CloudShellのRegion別永続領域と制限](https://docs.aws.amazon.com/cloudshell/latest/userguide/limits.html)
- [Amazon EKS pricing](https://aws.amazon.com/eks/pricing/)
- [Amazon CloudWatch pricing](https://aws.amazon.com/cloudwatch/pricing/)
- [Amazon EKS clusterの削除前確認](https://docs.aws.amazon.com/eks/latest/userguide/delete-cluster.html)
