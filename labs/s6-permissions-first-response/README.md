# Section 6: ServiceAccount・RBAC・IAMの関係を観察する

このハンズオンでは、コース共通のEKS環境を変更せずに、ServiceAccount、Kubernetes RBAC、EKS access entry、IRSA、EKS Pod Identityの関係を観察します。AWS Management Consoleから東京リージョンのAWS CloudShellを開き、Bashで実行します。

[Section 6のハンズオンリソースを開く](https://github.com/toma1110/udemy-aws-eks-kubernetes-operations-monitoring-handson/tree/main/labs/s6-permissions-first-response)

## 学習目標

1. ServiceAccountのannotationと、RoleBinding / ClusterRoleBindingのsubjectを確認する。
2. Kubernetes RBACとAWS IAMが別の判定層であることを、観察結果から説明する。
3. EKS access entry、IRSA、EKS Pod Identityが結ぶ対象の違いを確認する。
4. `Forbidden`、`Unauthorized`、`AccessDenied`、監視データ欠落の最初の確認先を選ぶ。

この演習は読み取りだけです。IAM policy、Kubernetes Role、RoleBinding、ClusterRoleBinding、EKS access entry、Pod Identity associationを作成・更新・削除しません。

## 1. CloudShellを開く

AWS Management Consoleで東京リージョン `ap-northeast-1` を選び、CloudShellを開きます。

```bash
export AWS_REGION="ap-northeast-1"
export AWS_DEFAULT_REGION="ap-northeast-1"
aws --version
kubectl version --client --output=json
printf 'HOME=%s\n' "$HOME"
df -h "$HOME"
```

期待結果:

- AWS CLIとkubectlのversionが表示される。
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

共通環境の通常の作成・削除contractはそのまま再利用します。共通の`status.sh`は詳細なAWS identityを表示するため、このSectionでは呼びません。次のSection-local statusが同じ固定stack、cluster、kube contextをprivate log内で検証し、terminalにはRegion、cluster状態、Ready Node数だけを表示します。

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
"$S6_DIR/scripts/status-redacted.sh"
"$S6_DIR/scripts/preflight.sh"
```

期待結果は、accountやARNを含まないcommon statusと `Preflight passed` です。run-specific directoryが既に存在する、temporary directoryが空でない、またはinstallation中にcollisionした場合は停止します。古いraw fileを再利用しません。

## 5. ServiceAccountとKubernetes RBACを確認する

```bash
kubectl get serviceaccount \
  "$TARGET_SERVICE_ACCOUNT" \
  -n "$TARGET_NAMESPACE" \
  -o json |
  jq '{
    namespace: .metadata.namespace,
    service_account: .metadata.name,
    irsa_annotation_present:
      (.metadata.annotations["eks.amazonaws.com/role-arn"] != null)
  }'

kubectl get rolebindings -A -o json
kubectl get clusterrolebindings -o json
```

確認する点:

- ServiceAccountのannotationに `eks.amazonaws.com/role-arn` があるか。あればIRSAの関連付け候補ですが、IAM roleの実効権限やtrust policyが正しいことまでは証明しません。
- RoleBinding / ClusterRoleBindingの`subjects`に対象ServiceAccountがあるか。
- bindingの`roleRef`がRoleかClusterRoleか。

bindingが見つからないことは、IAM権限がないことの証明ではありません。Kubernetes RBACとAWS IAMは別の層です。

## 6. AWS側の関係を観察して差をまとめる

次のscriptは、Kubernetesの`get`とAWSの`list` / `describe`だけを使います。生のAWS principal ARNを含む取得結果は`$S6_EVIDENCE_DIR/raw`へ保存し、画面にはaccount IDを含まない要約だけを表示します。

```bash
"$S6_DIR/scripts/capture-observations.sh"
python3 "$S6_DIR/analyze.py" \
  --input "$S6_EVIDENCE_DIR/raw" \
  --status "$S6_EVIDENCE_DIR/status" \
  --output "$S6_EVIDENCE_DIR/summary.json" \
  --namespace "$TARGET_NAMESPACE" \
  --service-account "$TARGET_SERVICE_ACCOUNT"
jq . "$S6_EVIDENCE_DIR/summary.json"
```

要約で比較する層:

- `kubernetes_rbac`: Kubernetes APIで対象ServiceAccountへ結ばれたRole / ClusterRole。
- `irsa_annotation`: ServiceAccount annotationが示すIAM roleとの関連付け候補。
- `pod_identity`: EKS Pod Identity associationが結ぶnamespace / ServiceAccount。`observed`と`not_observed_reason`を確認する。
- `eks_access`: IAM principalがEKS clusterへ入るためのaccess entry。PodのIAM権限そのものではない。listまたは個別describeが拒否された場合は`observed` / `complete`がfalseになる。

「関連付けがある」と「要求した操作が許可される」は同じではありません。初動では、errorが発生した層と、どの関連付けまで確認できたかを分けて記録します。
optionalなAWS readが拒否されても、scriptはprincipalやprovider error本文をterminalへ出さず、他の層の観察を続けます。`not observed`を`関連付けなし`と読み替えないでください。

## 7. AccessDeniedと監視データ欠落を切り分ける

| 観察した事実 | 最初に確認する層 | 次の安全な確認 |
| --- | --- | --- |
| `kubectl`が`Forbidden` | Kubernetes RBAC | errorのuser / ServiceAccount、verb、resource、namespaceとbindingを確認 |
| `kubectl`が`Unauthorized` | cluster認証 / credential | kubeconfig context、STS有効性、EKS access entryを管理者と確認 |
| AWS CLIやPod logに`AccessDenied` | AWS IAM | denied action、resource、利用主体、IRSA / Pod Identityのどちらを使うか確認 |
| commandは成功するがlog / metricがない | 収集経路または設定 | Agent Pod、設定、Region、時間範囲、log group / metric namespaceを確認 |

監視データがないだけで権限不足と決めません。逆に、明示的な`AccessDenied`をnetworkやデータ欠落として扱いません。このSectionでは権限を追加せず、事実を管理者へ渡すところまでを行います。

記録用templateをコピーできます。

```bash
cp "$S6_DIR/templates/observation-notes.md" \
  "$S6_EVIDENCE_DIR/observation-notes.md"
```

## 8. Cleanup

Section 6はAWS resourceもKubernetes resourceも作成しません。cleanupは2段階です。

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

Section 6の観察command自体は新しいresourceを作りません。主な費用は、既に稼働している共通EKS環境の利用時間です。共通環境は最大6時間以内に削除し、作成直前にEKS、EC2、EBS、public IPv4、CloudWatchの最新料金を公式ページで確認してください。実請求は利用時間、Region、税、割引、log量などで変わります。

## Troubleshooting

- `Preflight passed`にならない: 最初に表示されたerrorを保存し、後続commandを実行しません。
- `Forbidden`: この演習のためにRoleBindingを作らず、対象verb / resource / namespaceをcluster管理者へ共有します。
- `AccessDeniedException`: この演習のためにIAM policyやEKS access entryを追加せず、denied actionと実行主体をAWS管理者へ共有します。
- `ResourceNotFoundException`: Region、cluster名、namespace、ServiceAccount名を確認します。
- Pod Identity一覧を読めない: IRSA annotationやRBACの観察結果で代用したと表現せず、未確認として記録します。
- EKS access entryのlistまたはdescribeだけ拒否される: summaryの`observed` / `complete`を確認し、他の層の結果はそのまま利用します。
- run directory collision: 古いdirectoryを上書きせず、新しい`S6_RUN_ID`を作って最初から実行します。
- 削除後の確認が停止する: AWSアカウントの確認情報を手作業で消さず、共通EKS環境のリソースが残っていないか、実行中のAWSアカウントが変わっていないかを確認します。
- 要約がaccount IDを検出して停止する: raw fileは公開せず、`analyze.py`の要約対象を確認します。

## 公式資料

- [EKS access entries](https://docs.aws.amazon.com/eks/latest/userguide/access-entries.html)
- [IAM roles for service accounts](https://docs.aws.amazon.com/eks/latest/userguide/iam-roles-for-service-accounts.html)
- [EKS Pod Identity](https://docs.aws.amazon.com/eks/latest/userguide/pod-identities.html)
- [Kubernetes RBAC](https://kubernetes.io/docs/reference/access-authn-authz/rbac/)
