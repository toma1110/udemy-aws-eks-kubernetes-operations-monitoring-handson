# Section 6: ServiceAccount・RBAC・IAMの関係を観察する

このハンズオンでは、コース共通のEKS環境で、ServiceAccount、Kubernetes RBAC、IRSA、EKS Pod Identityの関係を観察します。1つの収集scriptで実行先を確認してから結果を取得し、`AccessDenied`や監視データ欠落の最初の確認先を選びます。AWS Management Consoleから東京リージョンのAWS CloudShellを開き、Bashで実行します。

[Section 6のハンズオンリソースを開く](https://github.com/toma1110/udemy-aws-eks-kubernetes-operations-monitoring-handson/tree/main/labs/s6-permissions-first-response)

## 学習目標

1. ServiceAccountのannotationと、RoleBinding / ClusterRoleBindingが結び付ける対象を確認する。
2. Kubernetes RBACとAWS IAMが別々に許可を判定することを、観察結果から説明する。
3. IRSAとEKS Pod IdentityはPodからAWS APIを使う仕組み、EKS access entryは人や運用ツールがclusterへ入るための設定として区別する。
4. `Forbidden`、`Unauthorized`、`AccessDenied`、監視データ欠落から、次に確認する情報を選ぶ。

この演習で行うAWSとKubernetesの操作は状態の取得だけです。権限設定の変更は演習範囲に含めず、必要な場合は観察メモを担当者へ渡します。

## 1. CloudShellを開く

AWS Management Consoleで東京リージョン `ap-northeast-1` を選び、CloudShellを開きます。

```bash
export AWS_REGION="ap-northeast-1"
export AWS_DEFAULT_REGION="ap-northeast-1"
aws --version
kubectl version --client --output=json
jq --version
printf 'HOME=%s\n' "$HOME"
df -h "$HOME"
```

期待結果:

- AWS CLI、kubectl、jqのversionが表示される。AWS CloudShellにはkubectlとjqがあらかじめ用意されていますが、versionは更新されるため、演習のたびに確認します。
- CloudShellの`$HOME`に空き容量がある。永続領域はRegionごとに1 GBです。

AWS Management Console上のaccount表示が利用予定と異なる場合は停止してください。STS identityは後の準備scriptがprivate fileへ保存し、accountやARNをterminalへ表示しません。

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

cd "$HANDSON_REPO/labs/s6-permissions-first-response"
export S6_DIR="$(pwd)"
chmod +x "$S6_DIR"/scripts/*.sh
```

## 3. 共通EKS環境を確認する

このSectionは、Section 5で使用した共通EKS環境を再利用します。環境がまだない場合だけ、[共通EKS環境のREADME](../common-eks/README.md)に従って作成してください。作成にはEKS control plane、managed node、EBS、public IPv4などの料金が発生します。

共通環境の作成と削除は、リンク先のREADMEに従います。このSectionでは、次の収集scriptが現在のAWS認証情報、Region、共通stack、cluster、`kubectl`の接続先を収集直前に確認します。AWSアカウントIDとARNは画面へ表示せず、CloudShell内の非公開fileに保存します。

```bash
export COMMON_EKS_DIR="$HANDSON_REPO/labs/common-eks"
```

## 4. 観察対象を選ぶ

既定では、共通clusterにある `kube-system/aws-node` ServiceAccountを観察します。別のServiceAccountを調べる場合は、実在するnamespaceと名前を明示します。

```bash
export TARGET_NAMESPACE="kube-system"
export TARGET_SERVICE_ACCOUNT="aws-node"
export S6_RUN_ID="$(date -u '+%Y%m%dT%H%M%SZ')-$(od -An -N4 -tx1 /dev/urandom | tr -d ' \n')"
export API_PUBLIC_ACCESS_CIDR="$(curl -fsS https://checkip.amazonaws.com | tr -d '[:space:]')/32"
source "$S6_DIR/scripts/prepare-private-run.sh"
```

期待結果は、`観察結果の保存先を準備しました`という表示です。保存先が既に存在する場合は停止するため、古い結果が今回の観察へ混ざりません。

## 5. 観察結果を取得する

次のscriptは、実行先とServiceAccountを確認した後、ServiceAccount、RoleBinding、ClusterRoleBinding、EKS access entry、Pod Identity associationを取得します。使用するAWS操作は`list`と`describe`、Kubernetes操作は`get`だけです。

```bash
"$S6_DIR/scripts/capture-observations.sh"
```

期待結果:

- Region、Namespace、ServiceAccountを示す`観察対象を確認しました`が表示される。
- `観察結果の取得が完了しました`が表示される。
- 生の取得結果は`$S6_EVIDENCE_DIR/raw`、取得できなかった項目の理由は`$S6_EVIDENCE_DIR/status`に保存される。

取得に失敗した場合は、その時点で停止し、最初に表示されたerrorを確認します。

## 6. 結果を整理する

次のプログラムは取得結果を読み、AWSアカウントIDやIAM ARNを含まない`summary.json`を作ります。

```bash
python3 "$S6_DIR/analyze.py" \
  --input "$S6_EVIDENCE_DIR/raw" \
  --status "$S6_EVIDENCE_DIR/status" \
  --output "$S6_EVIDENCE_DIR/summary.json" \
  --namespace "$TARGET_NAMESPACE" \
  --service-account "$TARGET_SERVICE_ACCOUNT"
jq . "$S6_EVIDENCE_DIR/summary.json"
```

結果の読み方:

- `kubernetes_rbac`: 対象ServiceAccountに結び付くRole / ClusterRole。
- `irsa_annotation`: IRSAで使うIAM roleのannotationがあるか。
- `pod_identity`: 対象NamespaceとServiceAccountに一致するPod Identity associationがあるか。
- `eks_access`: 人や運用ツールのIAM user / roleがclusterへ入るための設定。PodのAWS権限ではありません。

`observed`が`false`なら、その項目は確認できなかったという意味です。`complete`が`false`なら個別情報を最後まで取得できていないため、`target_association_present`は`null`になり、対象の関連付けがないとは判断できません。`not_observed_reason`へ記録された理由を確認します。また、関連付けが見つかっても、要求した操作が許可されることまでは証明しません。

## 7. AccessDeniedと監視データ欠落を切り分ける

| 観察した事実 | 最初に確認する層 | 次の安全な確認 |
| --- | --- | --- |
| `kubectl`が`Forbidden` | Kubernetes RBAC | errorに示された利用者またはServiceAccount、操作、resource、namespaceとbindingを確認 |
| `kubectl`が`Unauthorized` | cluster認証 / credential | kubeconfig context、STS有効性、EKS access entryを管理者と確認 |
| AWS CLIやPod logに`AccessDenied` | AWS IAM | denied action、resource、利用主体、IRSA / Pod Identityのどちらを使うか確認 |
| commandは成功するがlog / metricがない | 収集経路または設定 | Agent Pod、設定、Region、時間範囲、log group / metric namespaceを確認 |

監視データがないだけで権限不足と決めません。逆に、明示的な`AccessDenied`は拒否された操作と利用者を確認します。確認結果は次のtemplateへ記録します。

記録用templateをコピーできます。

```bash
cp "$S6_DIR/templates/observation-notes.md" \
  "$S6_EVIDENCE_DIR/observation-notes.md"
```

## 8. Cleanup

Section 6はAWS resourceもKubernetes resourceも作成しません。終了時は、Section 6の観察結果と共通EKS環境を別々に片付けます。

最初に、このSectionで保存した観察結果だけを削除します。共通EKS環境の削除が終わるまで、AWSアカウントの確認情報は残してください。

```bash
"$S6_DIR/scripts/cleanup-local-evidence.sh"
```

共通EKS環境をこの後使わない場合は、先に他Sectionのcleanupが終わっていることを確認し、共通環境を削除します。

```bash
"$COMMON_EKS_DIR/scripts/delete.sh"
```

共通EKS環境を削除した後、同じAWSアカウントで削除確認scriptを実行します。このscriptは、EKSと関連リソースが残っていないことを確かめてから、保存していたAWSアカウントの確認情報を削除します。

```bash
"$COMMON_EKS_DIR/scripts/post-guard-verify.sh"
```

共通EKS環境の削除または削除後の確認で、リソースの残り、AWSアカウントの不一致、権限エラーが表示された場合は、保存されたAWSアカウントの確認情報を手作業で消さず、[共通EKS環境のREADME](../common-eks/README.md)に従って解消してください。

## 費用

Section 6の観察では新しいresourceを作りません。主な費用は、既に稼働している共通EKS環境の利用時間です。共通環境は最大6時間以内に削除し、作成直前にEKS、EC2、EBS、public IPv4、CloudWatchの最新料金を公式ページで確認してください。実請求は利用時間、Region、税、割引、log量などで変わります。

## Troubleshooting

- 観察対象の確認で停止する: 最初に表示されたerrorを保存し、AWSアカウント、Region、共通stack、`kubectl`の接続先、ServiceAccount名を順に確認します。
- `Forbidden`: 対象の操作、resource、namespace、利用者またはServiceAccountをcluster管理者へ共有します。
- `AccessDeniedException`: denied action、resource、実行者またはPodのServiceAccountをAWS管理者へ共有します。
- `ResourceNotFoundException`: Region、cluster名、namespace、ServiceAccount名を確認します。
- Pod Identity一覧を読めない: IRSA annotationやRBACの観察結果で代用したと表現せず、未確認として記録します。
- EKS access entryのlistまたはdescribeだけ拒否される: summaryで未確認になった項目を記録し、他の項目の結果と混同しません。
- run directory collision: 古いdirectoryを上書きせず、新しい`S6_RUN_ID`を作って最初から実行します。
- 削除後の確認が停止する: AWSアカウントの確認情報を手作業で消さず、共通EKS環境のリソースが残っていないか、実行中のAWSアカウントが変わっていないかを確認します。
- 要約がAWSアカウントIDを検出して停止する: raw fileは共有せず、`analyze.py`の要約対象を確認します。

## 公式資料

- [AWS CloudShellの環境とプリインストール済みソフトウェア](https://docs.aws.amazon.com/cloudshell/latest/userguide/vm-specs.html)
- [AWS CloudShellのRegionと保存領域](https://docs.aws.amazon.com/cloudshell/latest/userguide/working-with-aws-cloudshell.html)
- [EKS access entries](https://docs.aws.amazon.com/eks/latest/userguide/access-entries.html)
- [IAM roles for service accounts](https://docs.aws.amazon.com/eks/latest/userguide/iam-roles-for-service-accounts.html)
- [EKS Pod Identity](https://docs.aws.amazon.com/eks/latest/userguide/pod-identities.html)
- [Kubernetes RBAC](https://kubernetes.io/docs/reference/access-authn-authz/rbac/)
