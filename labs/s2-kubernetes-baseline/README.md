# Section 2: 共通EKS上でKubernetes監視の基礎を確認する

このラボでは、共通EKS基盤へSection 2専用の小さなbaseline workloadを追加し、`kubectl get`、`describe`、`logs`、eventsで初動確認します。操作を行うhands-onは講義`s2-l3`と`s2-l4`です。

## 前提と安全境界

- 実行環境はAWS Management Consoleで東京Region (`ap-northeast-1`) を選んで起動したAWS CloudShellのBashです。local PowerShellは使いません。
- [共通EKS基盤](../common-eks/README.md)を作成し、`status.sh`が成功している必要があります。このラボは固定されたcommon commit/treeを実行時に検査し、共通基盤の変更を受け入れません。
- 共通基盤の出力をcommon scriptが読み戻し、現在のSTS identityとkubectl contextを照合します。値を手入力して照合を迂回しません。
- このSectionが作るのはNamespace、Deployment、ClusterIP Serviceだけです。LoadBalancer、Volume、CloudWatch、IAM、Node、EKS clusterは追加しません。
- 共通EKSには料金が発生します。実行直前にAWS公式料金を再確認し、最大6時間以内のcleanup deadlineを使ってください。Section終了後はSection cleanup、その後に共通cleanupを実行します。
- evidenceにはaccount ID、principal ARN、credential、private endpoint、個人情報を保存・共有しません。raw出力はGitへ追加しません。

## 1. CloudShell preflight

```bash
aws --version
kubectl version --client
aws sts get-caller-identity
echo "HOME=$HOME"
df -h "$HOME"
export AWS_REGION=ap-northeast-1
export AWS_DEFAULT_REGION=ap-northeast-1
```

出力されたaccountとprincipalが使用を許可されたexact identityであることを確認します。値は教材やGitへ貼りません。`$HOME`はCloudShellのRegion別1 GB永続領域なので、空き容量も確認します。

## 2. checkoutと共通基盤treeを確認する

repository rootで次を実行します。

```bash
BINDING=labs/s2-kubernetes-baseline/common-foundation.binding.json
COMMON_COMMIT="$(jq -er .common_foundation_commit "$BINDING")"
COMMON_TREE="$(jq -er .common_foundation_tree_oid "$BINDING")"
test "$(git rev-parse "$COMMON_COMMIT:labs/common-eks")" = "$COMMON_TREE"
test "$(git rev-parse "HEAD:labs/common-eks")" = "$COMMON_TREE"
bash labs/common-eks/scripts/status.sh
```

共通基盤をまだ作成していない場合は、先に[共通EKS基盤README](../common-eks/README.md)のcreate手順を完了します。

## 3. Section baseline workloadを作成する

```bash
bash labs/s2-kubernetes-baseline/scripts/apply-workload.sh
```

期待結果:

- Namespace `udemy4-c010-s2-baseline`が作成される。
- Deployment `baseline-web`のPodが1個`Ready`になる。
- ClusterIP Service `baseline-web`が同じlabelのPodを選択する。
- 共通EKSのNodeは`Ready`のままである。

## 4. `get`で全体を見る (`s2-l3`)

```bash
kubectl get nodes -o wide
kubectl get namespaces
kubectl get pods -A -o wide
kubectl get deployment,service,pods -n udemy4-c010-s2-baseline \
  -l udemy4.example/lab=s2-baseline -o wide
```

Cluster > Node > Namespace > Pod > Containerの順に所属を確認し、DeploymentがPodを維持し、Serviceがlabelで対象Podを選ぶことを確認します。

## 5. `describe`、`logs`、eventsで深掘りする (`s2-l4`)

```bash
POD_NAME="$(kubectl get pod -n udemy4-c010-s2-baseline \
  -l app.kubernetes.io/name=baseline-web \
  -o jsonpath='{.items[0].metadata.name}')"
test -n "$POD_NAME"

kubectl describe pod "$POD_NAME" -n udemy4-c010-s2-baseline
kubectl logs "$POD_NAME" -n udemy4-c010-s2-baseline --tail=100
kubectl get events -n udemy4-c010-s2-baseline \
  --sort-by=.metadata.creationTimestamp
kubectl get endpoints baseline-web -n udemy4-c010-s2-baseline -o wide
```

通常状態ではPodは`Running/Ready`、logには`baseline-started`とheartbeat、eventsにはscheduled/pulled/started等の履歴が表示されます。eventの文言や件数、Pod suffix、IP、時刻は環境で変わるため固定値として扱いません。

`Pending`、`CrashLoopBackOff`、`OOMKilled`はこのbaselineで意図的に発生させません。状態を見た場合は、まず`describe`のConditions/Events、`logs`と`logs --previous`、resource request/limitを確認します。[固定データの初動診断](../s2-kubernetes-initial-triage/README.md)は補助練習であり、AWS実結果の代わりにはしません。

## 6. 実結果をevidenceとして保存する

```bash
export EVIDENCE_DIR="$HOME/udemy-eks-evidence/s2-$(date -u +%Y%m%dT%H%M%SZ)"
bash labs/s2-kubernetes-baseline/scripts/verify-and-capture.sh
```

scriptはidentityそのものをfileへ書かず、account/principalをSHA-256にしてbindingへ保存します。共有前に全fileを確認し、secret、account ID、principal ARN、private address、local pathがないことを確認してください。

## 7. Section cleanup

共通EKSを削除する前に必ず実行します。

```bash
bash labs/s2-kubernetes-baseline/scripts/cleanup-section.sh
```

期待結果はNamespace照会がexit 0かつ空のstructured outputを返すことです。非zero、非empty、stderr内の`NotFound`文字列、認証・network・context・権限エラーはcleanup成功として扱いません。

## 8. 共通cleanupと残存確認

Section cleanup成功後、s2専用のfail-closed wrapperから共通基盤を削除します。

```bash
bash labs/s2-kubernetes-baseline/scripts/delete-common-after-s2.sh
```

wrapperはexact Namespaceの不存在をstructured照会で確認してからcommon `delete.sh`を呼びます。common scriptはCloudFormation/EKS/EC2/EBS/ENI/CloudWatchとcleanup guardの残存を検査します。両方が成功するまでcleanup完了と表現しません。

## トラブルシュート

- `CloudShell environment required`: AWS Consoleの東京RegionからCloudShellを起動し直します。
- identity/Region/context mismatch: 操作せず、STS identity、`AWS_REGION`、common stack出力、kubectl contextを照合します。
- PodがPending: `kubectl describe pod`のEventsでcapacity、taint、affinity、image pullを確認します。
- CrashLoopBackOff: current/previous logs、Last State、exit code、restart countを確認します。
- cleanupが失敗: 成功扱いにせず、権限、context、exact namespace ownership labelを確認します。

## Versionと料金

AWS CLIは`2.12.3`以上、`kubectl`はcluster versionと同じか前後1 minor以内を使います。workload imageは`public.ecr.aws/docker/library/busybox:1.36.1`に固定しています。EKS、EC2、EBS、public IPv4、CloudWatch等の料金は[共通EKS基盤README](../common-eks/README.md#cost-warning)のリンクから実行直前に再確認してください。
