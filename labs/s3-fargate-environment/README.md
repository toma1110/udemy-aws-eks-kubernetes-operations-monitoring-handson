# Section 3: 障害を戻せるFargate演習環境を準備する

この演習では、後続SectionでPod障害や権限エラーを1件ずつ安全に観察できる、専用の非本番EKS on AWS Fargate環境を準備します。AWS CloudShellのBashを既定環境にし、共有clusterや本番resourceは使いません。

> AWS上の実行結果はこの教材には含まれません。受講者自身の環境で表示されたactual outputを、下記の期待状態と照合して成功を判断してください。

## 到達点

- AWS identity、Region、cluster、Kubernetes context、namespace、料金要因、90分の時間上限を作成前に確認できる。
- 専用cluster、private subnet、Fargate Profile、Pod Execution Role、正常なsample application、Fargate logging、IRSA、RBACの関係を説明できる。
- 正常値、後続Sectionで加える障害差分、戻す値を`baseline-record.md`へ記録できる。
- 中断時は通常手順を続けず、`s10-l1-cleanup`「演習resourceを完全削除して残存を確認する」へ直行すると判断できる。

## 料金と停止条件

EKS cluster、Fargate vCPU／memory、private subnetのNAT Gateway、CloudWatch Logsの取り込み・保存・Logs Insights scanなどに料金が発生し得ます。料金はRegion、利用時間、通信量、ログ量、税、割引で変わります。実行直前に[EKS pricing](https://aws.amazon.com/eks/pricing/)、[Fargate pricing](https://aws.amazon.com/fargate/pricing/)、[CloudWatch pricing](https://aws.amazon.com/cloudwatch/pricing/)を確認してください。

この演習の上限は作成開始から90分です。次のいずれかなら新しい作成や障害注入を止め、`s10-l1-cleanup`へ進みます。

- identity、Region、cluster、context、namespace、対象resourceのどれかを一意に確認できない。
- 専用非本番環境であると確認できない、または共有resourceが対象に含まれる。
- 予算上限を決められない、90分以内に完了できない、権限追加の影響を説明できない。
- 作成が失敗した、正常値を確認できない、復旧値が不明、または中断する。

## 1. CloudShellで作業対象を固定する（s3-l1）

AWS Consoleで使用するRegionを選び、CloudShellを開きます。次の名前は教材全体で使うcanonical固定名です。1件でも既存resourceと衝突する場合は名前を変更、再利用、更新、削除せず、ここで停止して管理者へ確認してください。

```bash
export AWS_REGION="ap-northeast-1"
export AWS_DEFAULT_REGION="$AWS_REGION"
export CLUSTER_NAME="eks-fargate-ops-lab"
export NAMESPACE="eks-fargate-ops"
export FARGATE_PROFILE="ops-workloads"
export COREDNS_PROFILE="system-coredns"
export WORKLOAD_LABEL="ops-lab"
export MAX_MINUTES="90"
export STARTED_AT_UTC="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
```

identityは画面で確認しますが、account IDやARNをREADME、Issue、チャット、提出物へ貼り付けません。

### tool versionと必要権限のpreflight

次を実行し、versionを`baseline-record.md`へ記録します。

```bash
aws --version
eksctl version
kubectl version --client --output=yaml
python --version
```

- AWS CLIはCloudShellで提供されるversion 2を使います。
- `kubectl` clientは作成されるEKS control planeと同じminor、または前後1 minor以内を使います。
- `eksctl`はAWSの現行Fargate setup手順が要求する`0.215.0`以上を使います。`eksctl version`が`0.215.0`未満、判読不能、または実行失敗なら進みません。
- Python 3.11以上を使います。

実行identityには、この専用環境に限ったCloudFormation、EKS、EC2/VPC、IAM role/policy、CloudWatch Logsの作成・read・復旧・完全削除と`iam:PassRole`、および対象cluster内のnamespace／workload／RBAC操作が必要です。必要権限を管理者へ事前確認します。version条件を満たさない、または`AccessDenied`、credential、network errorが出た場合は、その場で権限やcredentialを追加・変更せず停止し、管理者へ確認します。

```bash
aws sts get-caller-identity
aws configure get region
printf 'REGION=%s CLUSTER=%s NAMESPACE=%s PROFILE=%s LIMIT=%smin START=%s\n' \
  "$AWS_REGION" "$CLUSTER_NAME" "$NAMESPACE" "$FARGATE_PROFILE" "$MAX_MINUTES" "$STARTED_AT_UTC"
```

canonical固定名のcluster、IAM policy、IAM role、CloudWatch log groupをread-onlyで確認します。すべて不存在である場合だけ進みます。`ResourceNotFoundException`、IAMの`NoSuchEntity`、log group検索の空配列は、それぞれのAPIが成功した場合だけ「候補なし」です。permission、network、credentialのerrorを不存在と読み替えません。

```bash
if CLUSTER_CHECK="$(aws eks describe-cluster --region "$AWS_REGION" --name "$CLUSTER_NAME" 2>&1)"; then
  printf 'STOP: canonical cluster already exists; do not reuse or modify it.\n' >&2
  unset CLUSTER_CHECK
  exit 1
elif grep -Fq 'An error occurred (ResourceNotFoundException) when calling the DescribeCluster operation:' <<<"$CLUSTER_CHECK" && grep -Fq "No cluster found for name: $CLUSTER_NAME." <<<"$CLUSTER_CHECK"; then
  unset CLUSTER_CHECK
else
  printf 'STOP: cluster absence was not proven by EKS DescribeCluster; ask the administrator.\n' >&2
  unset CLUSTER_CHECK
  exit 1
fi
if CALLER_ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text 2>&1)" && [[ "$CALLER_ACCOUNT_ID" =~ ^[0-9]{12}$ ]]; then
  export CALLER_ACCOUNT_ID
else
  printf 'STOP: the caller account ID was not obtained exactly; ask the administrator.\n' >&2
  unset CALLER_ACCOUNT_ID
  exit 1
fi
export CANONICAL_IRSA_POLICY_ARN="arn:aws:iam::$CALLER_ACCOUNT_ID:policy/eks-fargate-ops-describe-cluster"
if IAM_POLICY_CHECK="$(aws iam get-policy --policy-arn "$CANONICAL_IRSA_POLICY_ARN" 2>&1)"; then
  printf 'STOP: canonical IAM policy already exists; do not reuse or modify it.\n' >&2
  unset IAM_POLICY_CHECK CALLER_ACCOUNT_ID CANONICAL_IRSA_POLICY_ARN
  exit 1
elif grep -Fq 'An error occurred (NoSuchEntity) when calling the GetPolicy operation:' <<<"$IAM_POLICY_CHECK" && grep -Fq "$CANONICAL_IRSA_POLICY_ARN" <<<"$IAM_POLICY_CHECK" && grep -Fq 'was not found' <<<"$IAM_POLICY_CHECK"; then
  unset IAM_POLICY_CHECK
else
  printf 'STOP: IAM policy absence was not proven by IAM GetPolicy; ask the administrator.\n' >&2
  unset IAM_POLICY_CHECK CALLER_ACCOUNT_ID CANONICAL_IRSA_POLICY_ARN
  exit 1
fi
if IAM_ROLE_CHECK="$(aws iam get-role --role-name eks-fargate-ops-irsa-reader 2>&1)"; then
  printf 'STOP: canonical IAM role already exists; do not reuse or modify it.\n' >&2
  unset IAM_ROLE_CHECK CALLER_ACCOUNT_ID CANONICAL_IRSA_POLICY_ARN
  exit 1
elif grep -Fq 'An error occurred (NoSuchEntity) when calling the GetRole operation:' <<<"$IAM_ROLE_CHECK" && grep -Fq 'The role with name eks-fargate-ops-irsa-reader cannot be found.' <<<"$IAM_ROLE_CHECK"; then
  unset IAM_ROLE_CHECK
else
  printf 'STOP: IAM role absence was not proven; ask the administrator.\n' >&2
  unset IAM_ROLE_CHECK CALLER_ACCOUNT_ID CANONICAL_IRSA_POLICY_ARN
  exit 1
fi
if LOG_GROUP_MATCH_COUNT="$(aws logs describe-log-groups --region "$AWS_REGION" --log-group-name-prefix /aws/eks/eks-fargate-ops-lab/containers --query 'length(logGroups[?logGroupName==`/aws/eks/eks-fargate-ops-lab/containers`])' --output text 2>&1)"; then
  if [[ "$LOG_GROUP_MATCH_COUNT" == "0" ]]; then
    unset LOG_GROUP_MATCH_COUNT
  else
    printf 'STOP: canonical CloudWatch log group exists or the exact count is indeterminate; do not reuse or modify it.\n' >&2
    unset LOG_GROUP_MATCH_COUNT CALLER_ACCOUNT_ID CANONICAL_IRSA_POLICY_ARN
    exit 1
  fi
else
  printf 'STOP: log group absence was not proven by CloudWatch Logs DescribeLogGroups; ask the administrator.\n' >&2
  unset LOG_GROUP_MATCH_COUNT CALLER_ACCOUNT_ID CANONICAL_IRSA_POLICY_ARN
  exit 1
fi
unset CALLER_ACCOUNT_ID CANONICAL_IRSA_POLICY_ARN
```

同名resourceが存在する場合は所有者を推測して再利用・更新・削除しません。canonical名を別名へ変えず、ここで停止します。cluster作成後、namespaceが既に存在していた場合も適用を続けず停止します。

## 2. 配布ファイルをローカル検査する

このREADMEがあるdirectoryで実行します。`render_validate.py`はAWSへ接続せず、placeholder、固定名、正常値、復旧表、manifestの構造を検査します。

```bash
python render_validate.py --check
python -m unittest discover -s tests -v
```

期待結果:

```text
PASS: Section 3 templates satisfy the local safety contract
```

## 3. EKS clusterとFargate Profileを準備する（s3-l2）

Fargate Podはprivate subnetへ配置されます。`templates/cluster.yaml`は`eksctl`の既定VPC topologyと単一NAT Gatewayを使い、workload用Profileに加えてCoreDNS用Profileを作ります。subnet数は固定値として断定せず、作成後にProfileが返す実際の値をread-onlyで確認します。作成前にファイルを開き、cluster名、Region、namespace、label、2つのFargate Profileが上記のcanonical固定値と一致することを確認します。

```bash
if eksctl create cluster -f templates/cluster.yaml; then
  printf 'Cluster creation succeeded; continuing to kubeconfig update.\n'
else
  printf 'STOP: cluster creation failed; do not run update-kubeconfig or later mutation commands. Go to s10-l1-cleanup.\n' >&2
  exit 1
fi
if aws eks update-kubeconfig --region "$AWS_REGION" --name "$CLUSTER_NAME"; then
  printf 'kubeconfig update succeeded; proving the exact intended EKS context.\n'
else
  printf 'STOP: update-kubeconfig failed; do not run namespace lookup or kubectl mutation commands.\n' >&2
  exit 1
fi
if CONTEXT_ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text 2>&1)" && [[ "$CONTEXT_ACCOUNT_ID" =~ ^[0-9]{12}$ ]]; then
  export EXPECTED_EKS_CONTEXT="arn:aws:eks:${AWS_REGION}:${CONTEXT_ACCOUNT_ID}:cluster/${CLUSTER_NAME}"
else
  printf 'STOP: the account ID for exact context verification was not obtained.\n' >&2
  unset CONTEXT_ACCOUNT_ID EXPECTED_EKS_CONTEXT
  exit 1
fi
if CURRENT_CONTEXT="$(kubectl config current-context 2>&1)" && [[ "$CURRENT_CONTEXT" == "$EXPECTED_EKS_CONTEXT" ]]; then
  printf 'Verified exact EKS context: %s\n' "$CURRENT_CONTEXT"
else
  printf 'STOP: current context is empty, unreadable, or not exactly the intended EKS context ARN.\n' >&2
  unset CURRENT_CONTEXT CONTEXT_ACCOUNT_ID EXPECTED_EKS_CONTEXT
  exit 1
fi
unset CURRENT_CONTEXT CONTEXT_ACCOUNT_ID EXPECTED_EKS_CONTEXT
if NAMESPACE_CHECK="$(kubectl get namespace "$NAMESPACE" -o name 2>&1)"; then
  printf 'STOP: canonical namespace already exists; do not apply, reuse, or modify it.\n' >&2
  unset NAMESPACE_CHECK
  exit 1
elif grep -q '(NotFound)' <<<"$NAMESPACE_CHECK" && grep -q "namespaces \"$NAMESPACE\" not found" <<<"$NAMESPACE_CHECK"; then
  unset NAMESPACE_CHECK
else
  printf 'STOP: namespace absence was not proven by the API; ask the administrator.\n' >&2
  unset NAMESPACE_CHECK
  exit 1
fi
aws eks describe-fargate-profile --region "$AWS_REGION" --cluster-name "$CLUSTER_NAME" --fargate-profile-name "$FARGATE_PROFILE" --query 'fargateProfile.{status:status,subnets:subnets,selectors:selectors,podExecutionRoleArn:podExecutionRoleArn}' --output json
aws eks describe-fargate-profile --region "$AWS_REGION" --cluster-name "$CLUSTER_NAME" --fargate-profile-name "$COREDNS_PROFILE" --query 'fargateProfile.{status:status,subnets:subnets,selectors:selectors}' --output json
export FARGATE_SUBNET_IDS="$(aws eks describe-fargate-profile --region "$AWS_REGION" --cluster-name "$CLUSTER_NAME" --fargate-profile-name "$FARGATE_PROFILE" --query 'fargateProfile.subnets' --output text)"
aws ec2 describe-subnets --region "$AWS_REGION" --subnet-ids $FARGATE_SUBNET_IDS --query 'Subnets[].{SubnetId:SubnetId,AZ:AvailabilityZone,MapPublicIp:MapPublicIpOnLaunch}' --output table
for subnet_id in $FARGATE_SUBNET_IDS; do aws ec2 describe-route-tables --region "$AWS_REGION" --filters "Name=association.subnet-id,Values=$subnet_id" --query 'RouteTables[].{RouteTableId:RouteTableId,Routes:Routes}' --output json; done
kubectl rollout status deployment/coredns -n kube-system --timeout=10m
kubectl get deployment coredns -n kube-system -o custom-columns=NAME:.metadata.name,DESIRED:.spec.replicas,READY:.status.readyReplicas,AVAILABLE:.status.availableReplicas
```

期待状態:

- clusterとworkload/CoreDNSの両Fargate Profileが`ACTIVE`。
- Profile selectorがnamespace `eks-fargate-ops`かつlabel `compute=ops-lab`。
- CoreDNS Profile selectorがnamespace `kube-system`かつlabel `k8s-app=kube-dns`。
- workload Profileが返した実際のsubnet数／IDを記録し、各subnetがpublic IPを自動付与せず、route tableにInternet Gatewayへのdirect routeがないprivate subnetである。
- CoreDNS DeploymentのReadyとavailableがdesiredに一致する。
- `kubectl config current-context`がこのclusterのcontextである。

Fargate Profileは変更できません。selectorやsubnetが違う場合にその場で上書きせず、作成を中止して`s10-l1-cleanup`の完全削除後に設計を直します。

## 4. 正常なsample applicationを配置する（s3-l3）

namespace、ConfigMap、Secret、ServiceAccount、Deploymentを適用します。Secretは学習用の非機密文字列だけで、実credentialを入れません。

```bash
kubectl apply -f templates/application.yaml
kubectl rollout status deployment/baseline-app -n "$NAMESPACE" --timeout=5m
kubectl get pods -n "$NAMESPACE" -l app=baseline-app -o wide
kubectl describe pods -n "$NAMESPACE" -l app=baseline-app
kubectl logs -n "$NAMESPACE" deployment/baseline-app --tail=20
```

正常値は、Podが`Running`、Readyが`1/1`、restartが`0`、Fargateへ配置され、ログに`level=INFO app=baseline-app config=baseline secret_ref=loaded`が繰り返し出ることです。実際のPod名、観察UTC時刻、状態、restart数、ログ1行を`baseline-record.md`へ記録します。Secretの値は記録しません。

## 5. FargateログをCloudWatch Logsへ転送する（s3-l4）

組み込みlog routerは`aws-observability` namespaceのConfigMapを検出します。まず専用log groupを作成します。次にPod Execution Role名を取得し、公式の`AmazonEKSFargatePodExecutionRolePolicy`に加えて、このlog groupへの送信policyだけを付与します。role ARNやaccount IDを提出物へ保存しません。

```bash
if aws logs create-log-group --region "$AWS_REGION" --log-group-name /aws/eks/eks-fargate-ops-lab/containers; then
  if ! aws logs put-retention-policy --region "$AWS_REGION" --log-group-name /aws/eks/eks-fargate-ops-lab/containers --retention-in-days 1; then
    printf 'STOP: setting log retention failed; do not continue logging mutation.\n' >&2
    exit 1
  fi
  if ! POD_EXECUTION_ROLE_ARN="$(aws eks describe-fargate-profile --region "$AWS_REGION" --cluster-name "$CLUSTER_NAME" --fargate-profile-name "$FARGATE_PROFILE" --query 'fargateProfile.podExecutionRoleArn' --output text)" || [[ -z "$POD_EXECUTION_ROLE_ARN" || "$POD_EXECUTION_ROLE_ARN" == "None" ]]; then
    printf 'STOP: Pod Execution Role ARN was not obtained; do not continue logging mutation.\n' >&2
    unset POD_EXECUTION_ROLE_ARN
    exit 1
  fi
  export POD_EXECUTION_ROLE_ARN
  export POD_EXECUTION_ROLE_NAME="${POD_EXECUTION_ROLE_ARN##*/}"
  if ! aws iam put-role-policy --role-name "$POD_EXECUTION_ROLE_NAME" --policy-name eks-fargate-ops-logging --policy-document file://templates/pod-execution-logging-policy.json; then
    printf 'STOP: attaching the logging policy failed; do not apply the logging ConfigMap.\n' >&2
    exit 1
  fi
  if ! kubectl apply -f templates/logging.yaml; then
    printf 'STOP: applying the logging ConfigMap failed; do not restart the workload.\n' >&2
    exit 1
  fi
  if ! kubectl rollout restart deployment/baseline-app -n "$NAMESPACE"; then
    printf 'STOP: workload restart failed; do not continue.\n' >&2
    exit 1
  fi
  if ! kubectl rollout status deployment/baseline-app -n "$NAMESPACE" --timeout=5m; then
    printf 'STOP: restarted workload did not become ready; go to s10-l1-cleanup.\n' >&2
    exit 1
  fi
else
  printf 'STOP: create-log-group failed (including race/existence, permission, network, or credential errors); do not set retention or run later logging mutation.\n' >&2
  exit 1
fi
```

CloudWatch Logsで`/aws/eks/eks-fargate-ops-lab/containers`を開き、Regionと直近15分へ絞ります。log streamのKubernetes metadataでnamespace、Pod、containerが対象と一致し、上記INFOログが到着することを確認します。0件は正常と断定せず、Podの標準出力、ConfigMap、Pod Execution Role、Region、log groupの順に戻ります。

## 6. IRSAとRBACの検証対象を用意する（s3-l5）

IRSAはPod内applicationのAWS API用です。Pod Execution Roleとは別です。OIDC providerを関連付け、専用ServiceAccountへこのclusterの`eks:DescribeCluster`だけを許可します。preflightで同名IAM policyが不存在と確認できていない場合は作成や再利用をせず停止します。

次の各gateは直前の成功時だけ次へ進みます。どこかで停止した場合、それまでに作成済みのOIDC依存、IAM policy/role、ServiceAccount、RBAC、Jobはpartial resourceとして`s10-l1-cleanup`の対象に含めます。この場で推測してinline削除せず、後続のIAM/Kubernetes mutationも実行しません。

```bash
if eksctl utils associate-iam-oidc-provider --region "$AWS_REGION" --cluster "$CLUSTER_NAME" --approve; then
  printf 'OIDC provider association succeeded.\n'
else
  printf 'STOP: OIDC provider association failed; go to s10-l1-cleanup and do not continue IAM/Kubernetes mutation.\n' >&2
  exit 1
fi
if IRSA_ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text 2>&1)" && [[ "$IRSA_ACCOUNT_ID" =~ ^[0-9]{12}$ ]]; then
  export IRSA_ACCOUNT_ID
  export EXPECTED_IRSA_POLICY_ARN="arn:aws:iam::${IRSA_ACCOUNT_ID}:policy/eks-fargate-ops-describe-cluster"
else
  printf 'STOP: current STS account ID is empty, malformed, or unavailable; go to s10-l1-cleanup.\n' >&2
  unset IRSA_ACCOUNT_ID EXPECTED_IRSA_POLICY_ARN
  exit 1
fi
if IRSA_POLICY_ARN="$(aws iam create-policy --policy-name eks-fargate-ops-describe-cluster --policy-document file://templates/irsa-policy.json --query 'Policy.Arn' --output text 2>&1)"; then
  if [[ "$IRSA_POLICY_ARN" =~ ^arn:aws:iam::[0-9]{12}:policy/eks-fargate-ops-describe-cluster$ && "$IRSA_POLICY_ARN" == "$EXPECTED_IRSA_POLICY_ARN" ]]; then
    export IRSA_POLICY_ARN
  else
    printf 'STOP: create-policy returned an empty, malformed, wrong-account, or wrong-name ARN; include any created policy in s10-l1-cleanup and do not continue.\n' >&2
    unset IRSA_POLICY_ARN IRSA_ACCOUNT_ID EXPECTED_IRSA_POLICY_ARN
    exit 1
  fi
else
  printf 'STOP: create-policy failed; include any partial policy in s10-l1-cleanup and do not continue.\n' >&2
  unset IRSA_POLICY_ARN IRSA_ACCOUNT_ID EXPECTED_IRSA_POLICY_ARN
  exit 1
fi
if eksctl create iamserviceaccount --region "$AWS_REGION" --cluster "$CLUSTER_NAME" --namespace "$NAMESPACE" --name irsa-reader --role-name eks-fargate-ops-irsa-reader --attach-policy-arn "$IRSA_POLICY_ARN" --approve; then
  printf 'IRSA ServiceAccount creation succeeded.\n'
else
  printf 'STOP: IRSA ServiceAccount creation failed; include partial IAM/Kubernetes resources in s10-l1-cleanup and do not continue.\n' >&2
  exit 1
fi
if kubectl apply -f templates/rbac.yaml; then
  printf 'Read-only RBAC target apply succeeded.\n'
else
  printf 'STOP: RBAC apply failed; include partial RBAC resources in s10-l1-cleanup and do not continue.\n' >&2
  exit 1
fi
if kubectl apply -f templates/irsa-check.yaml; then
  printf 'IRSA check Job apply succeeded.\n'
else
  printf 'STOP: IRSA Job apply failed; include any partial Job in s10-l1-cleanup and do not continue.\n' >&2
  exit 1
fi
if kubectl wait --for=condition=complete job/irsa-describe-cluster -n "$NAMESPACE" --timeout=5m; then
  printf 'IRSA check Job reported Complete within the timeout.\n'
else
  printf 'STOP: IRSA Job wait failed or timed out; go to s10-l1-cleanup and do not continue.\n' >&2
  exit 1
fi
if IRSA_JOB_LOG="$(kubectl logs job/irsa-describe-cluster -n "$NAMESPACE" 2>&1)" && [[ "$IRSA_JOB_LOG" == "ACTIVE" ]]; then
  printf 'IRSA check log matched exact expected value ACTIVE.\n'
else
  printf 'STOP: IRSA Job log failed or was not exactly ACTIVE; go to s10-l1-cleanup and do not continue.\n' >&2
  unset IRSA_JOB_LOG
  exit 1
fi
if IRSA_JOB_COMPLETE="$(kubectl get job irsa-describe-cluster -n "$NAMESPACE" -o jsonpath='{.status.conditions[?(@.type=="Complete")].status}' 2>&1)" && [[ "$IRSA_JOB_COMPLETE" == "True" ]]; then
  printf 'IRSA Job Complete condition matched exact expected value True.\n'
else
  printf 'STOP: IRSA Job Complete condition was empty, unreadable, or not exactly True; go to s10-l1-cleanup.\n' >&2
  unset IRSA_JOB_LOG IRSA_JOB_COMPLETE
  exit 1
fi
if RBAC_CAN_GET="$(kubectl auth can-i get configmaps --as=system:serviceaccount:"$NAMESPACE":rbac-reader -n "$NAMESPACE" 2>&1)" && [[ "$RBAC_CAN_GET" == "yes" ]]; then
  printf 'RBAC get check matched exact expected value yes.\n'
else
  printf 'STOP: RBAC get check failed or was not exactly yes; go to s10-l1-cleanup.\n' >&2
  unset RBAC_CAN_GET
  exit 1
fi
if RBAC_CAN_DELETE="$(kubectl auth can-i delete configmaps --as=system:serviceaccount:"$NAMESPACE":rbac-reader -n "$NAMESPACE" 2>&1)" && [[ "$RBAC_CAN_DELETE" == "no" ]]; then
  printf 'RBAC delete check matched exact expected value no.\n'
else
  printf 'STOP: RBAC delete check failed or was not exactly no; go to s10-l1-cleanup.\n' >&2
  unset RBAC_CAN_DELETE
  exit 1
fi
unset IRSA_ACCOUNT_ID EXPECTED_IRSA_POLICY_ARN IRSA_JOB_LOG IRSA_JOB_COMPLETE RBAC_CAN_GET RBAC_CAN_DELETE
```

IRSA Jobはversion固定AWS CLI `2.27.49`を使い、`irsa-reader` ServiceAccountでこのclusterの`eks:DescribeCluster`を呼びます。期待ログは`ACTIVE`、Jobは`Complete`です。実際に表示された結果とimage versionを`baseline-record.md`へ記録し、期待状態と一致しなければ次へ進みません。

RBACの期待状態は`get configmaps`が`yes`、`delete configmaps`が`no`です。IRSA ServiceAccountには`eks.amazonaws.com/role-arn` annotationが1件あり、RBAC用`rbac-reader`とは別主体です。ここでは広い管理者権限を付けません。

## 7. 正常値・障害差分・復旧値を確認する（s3-l6）

後続Sectionでは一度に1つだけ差分を加えます。開始前に次の表と現在値を比較し、違えば障害注入へ進みません。

| 対象 | 正常値 | 後続で加える差分例 | 復旧値 |
| --- | --- | --- | --- |
| Fargate selector | namespace `eks-fargate-ops`、`compute=ops-lab` | Pod label不一致 | `compute=ops-lab` |
| application ConfigMap | `APP_MODE=baseline` | 起動不能な設定 | `APP_MODE=baseline` |
| probe | `/tmp/healthy`をexecで確認 | 存在しないpath | `/tmp/healthy` |
| IRSA | `irsa-reader`のrole annotation | annotation欠落／誤り | 作成時のexact role ARN |
| RBAC | `get configmaps=yes`、`delete configmaps=no` | RoleBinding subject不一致 | `rbac-reader` |
| logging | `aws-observability/aws-logging`、専用log group、保持1日 | output設定不一致 | `templates/logging.yaml`と保持1日 |

```bash
kubectl get deployment,configmap,serviceaccount,role,rolebinding -n "$NAMESPACE" -o yaml
kubectl get configmap aws-logging -n aws-observability -o yaml
kubectl get pods -n "$NAMESPACE" -l app=baseline-app
kubectl logs -n "$NAMESPACE" deployment/baseline-app --tail=5
kubectl get job irsa-describe-cluster -n "$NAMESPACE"
kubectl logs job/irsa-describe-cluster -n "$NAMESPACE"
```

各シナリオの観察後は対応するtemplateを再適用し、Podが`Running`／Ready `1/1`、restart増加が止まり、正常ログが再び出ることを確認します。変更前後の対象、UTC時刻、症状、根拠、復旧確認だけを記録し、credentialやSecret値は残しません。

## 中断・終了

このSectionではCourse共通resourceを完全削除しません。中断時、90分到達時、作成失敗時、またはCourse終了時は、通常の学習順を飛ばしてUdemyの`s10-l1-cleanup`「演習resourceを完全削除して残存を確認する」へ直行してください。namespace、logging ConfigMap、Fargate Profile、IRSA role/policy/OIDC依存、Pod Execution Role、cluster、NAT Gateway、VPC、CloudWatch Logsを作成逆順と依存関係に沿って削除し、EKS/Fargate/IAM/CloudWatch Logs/VPCの残存0をread-onlyで確認するまでは完了ではありません。共有resourceは削除しません。

## Troubleshooting

- `AccessDenied`: 権限を追加して試行を続けず、拒否されたaction、対象、使用identityを管理者へ確認します。
- Podが`Pending`: Profileのnamespace／label selector、private subnet、Pod Execution Role、Eventsを順に確認します。
- `ImagePullBackOff`: image名、network経路、Pod Execution Roleを確認します。Pod内applicationのIRSAと混同しません。
- logging ConfigMapが拒否される: keyが`filters.conf`／`output.conf`／`parsers.conf`の許可範囲か、`[INPUT]`や`[SERVICE]`を含めていないか確認します。
- IRSAが機能しない: clusterのOIDC provider、ServiceAccount annotation、trustのnamespace／ServiceAccount、Podが使うServiceAccountを照合します。
- `Forbidden`: Kubernetes RBACを確認します。AWS IAM policyを広げて解決しません。

## 公式資料（2026-08-06確認）

- [CloudShellからEKSへ接続する](https://docs.aws.amazon.com/eks/latest/userguide/create-kubeconfig.html)
- [Amazon EKSでFargateを開始する（eksctl 0.215.0以上、CoreDNSを含む）](https://docs.aws.amazon.com/eks/latest/userguide/fargate-getting-started.html)
- [Fargate Profileとprivate subnet](https://docs.aws.amazon.com/eks/latest/userguide/fargate-profile.html)
- [Fargate logging](https://docs.aws.amazon.com/eks/latest/userguide/fargate-logging.html)
- [Pod Execution Role](https://docs.aws.amazon.com/eks/latest/userguide/pod-execution-role.html)
- [IRSA](https://docs.aws.amazon.com/eks/latest/userguide/iam-roles-for-service-accounts.html)
