# Section 2: 共通EKSでKubernetes監視の基礎を確認する

このラボでは、共通EKSへ小さなWebアプリを追加し、`kubectl get`、`describe`、`logs`、eventsを使って状態を確認します。操作する講義は`s2-l3`と`s2-l4`です。

## 前提と安全上の注意

- AWS Management Consoleで東京リージョン（`ap-northeast-1`）を選び、AWS CloudShellのBashを使います。
- 先に[共通EKS基盤](../common-eks/README.md)を作成し、`status.sh`が成功することを確認します。
- 使用を許可されたAWSアカウント、東京リージョン、対象クラスターが一致することを確認します。不一致が表示された場合は、接続先を直してからもう一度確認してください。
- このラボが追加するのはNamespace、Deployment、ClusterIP Serviceだけです。LoadBalancer、Volume、CloudWatch、IAM、Node、EKSクラスターは追加しません。
- EKSなどの利用料金が発生します。実行直前にAWS公式料金を確認し、最大6時間以内に削除を始めてください。
- アカウントID、principal ARN、認証情報、非公開アドレス、個人情報を教材や共有ファイルへ貼らないでください。

## 1. CloudShellを確認する

ここでは、`aws --version`と`kubectl version --client`で必要な道具を確認し、`aws sts get-caller-identity`で操作先の利用者を確認します。`echo`と`df`はCloudShellの保存先と空き容量、`export`は以降のAWS CLIを東京リージョンへ固定するために使います。

```bash
aws --version
kubectl version --client
aws sts get-caller-identity
echo "HOME=$HOME"
df -h "$HOME"
export AWS_REGION=ap-northeast-1
export AWS_DEFAULT_REGION=ap-northeast-1
```

表示されたアカウントと利用者が、使用を許可されたものと一致することを確認します。`$HOME`の空き容量も確認してください。

## 2. 共通EKSの状態を確認する

教材の先頭ディレクトリで実行します。

`status.sh`の目的は、作成処理の前に接続先、共通EKS、Nodeの状態をread-onlyで確認することです。

```bash
bash labs/common-eks/scripts/status.sh
```

成功しない場合は先へ進みません。[共通EKS基盤README](../common-eks/README.md)の作成手順またはトラブルシュートを確認してください。

## 3. Section 2のアプリを作成する

`apply-workload.sh`の目的は、このSection専用Namespaceへ、観察対象となるDeploymentとClusterIP Serviceだけを作成することです。既存の同名Namespaceは更新も流用もしません。

```bash
bash labs/s2-kubernetes-baseline/scripts/apply-workload.sh
```

期待結果:

- Namespace `udemy4-c010-s2-baseline`が作成される
- Deployment `baseline-web`のPodが1個`Ready`になる
- ClusterIP Service `baseline-web`が対象Podを選択する
- 共通EKSのNodeが`Ready`のままである

同名Namespaceがすでに存在するというメッセージが表示された場合は、作成済みのリソースと接続先を確認してください。既存のNamespaceへ新しいリソースを追加せず、不要な学習用Namespaceであることを確認できた場合だけ、手順7で削除してからやり直します。

## 4. `get`で全体を見る（`s2-l3`）

目的は、広い一覧からSection専用workloadまで順に範囲を狭めることです。最初の3コマンドでNode、Namespace、全Podの影響範囲を確認し、最後のコマンドでSectionのLabelが付いたDeployment、Service、Podだけへ絞ります。

```bash
kubectl get nodes -o wide
kubectl get namespaces
kubectl get pods -A -o wide
kubectl get deployment,service,pods -n udemy4-c010-s2-baseline \
  -l udemy4.example/lab=s2-baseline -o wide
```

Cluster、Node、Namespace、Pod、Containerの順に所属を確認します。DeploymentがPodを維持し、Serviceがラベルで対象Podを選んでいることも確認します。

## 5. `describe`、`logs`、eventsで詳しく見る（`s2-l4`）

最初の2行はLabelから対象Pod名を1件取得できたことを確認します。`describe`は状態理由とContainerの履歴、`logs`はアプリの出力、eventsは周辺で起きた出来事、`endpoints`はServiceがどのPodへ接続するかを確認するために使います。

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

通常はPodが`Running/Ready`になり、ログに`baseline-started`とheartbeat、eventsにscheduled、pulled、startedなどが表示されます。Pod名の末尾、IP、時刻、eventの文言や件数は環境ごとに変わります。

`Pending`、`CrashLoopBackOff`、`OOMKilled`が表示された場合は、`describe`のConditionsとEvents、`logs`と`logs --previous`、resource requestとlimitを確認します。

## 6. 確認結果を保存する

`EVIDENCE_DIR`は今回の観察結果だけを保存する新しいディレクトリを指定します。`verify-and-capture.sh`の目的は、Pod、Deployment、Serviceの対応と期待ログを確認し、cleanup前の観察結果をそのディレクトリへ保存することです。

```bash
export EVIDENCE_DIR="$HOME/udemy-eks-evidence/s2-$(date -u +%Y%m%dT%H%M%SZ)"
bash labs/s2-kubernetes-baseline/scripts/verify-and-capture.sh
```

共有前に保存ファイルを開き、認証情報、アカウントID、principal ARN、非公開アドレス、個人情報が含まれていないことを確認してください。

## 7. Section 2のリソースを削除する

共通EKSを削除する前に必ず実行します。

`cleanup-section.sh`の目的は、この教材のLabelを持つ正確なSection 2 Namespaceだけを削除し、同名Namespaceが残っていないことまで確認することです。接続先またはNamespaceの確認に失敗した場合は削除せず、原因を確認します。

```bash
bash labs/s2-kubernetes-baseline/scripts/cleanup-section.sh
```

Namespaceがないことを正常に確認できた場合だけ成功です。認証、ネットワーク、接続先、権限のエラーや、確認できない結果は成功として扱いません。

## 8. 共通EKSを削除して残存を確認する

Section 2の削除に成功した後で実行します。

`delete-common-after-s2.sh`の目的は、Section 2 Namespaceの不存在を再確認したうえで、共通EKSの削除と残存確認を続けることです。ほかの用途で共通EKSを使っている場合は、この手順を実行しません。

```bash
bash labs/s2-kubernetes-baseline/scripts/delete-common-after-s2.sh
```

このスクリプトはSection 2のNamespaceがないことを確認してから、共通EKSを削除します。CloudFormation、EKS、EC2、EBS、ENI、CloudWatchなどの残存やエラーが表示された場合は、該当する項目を確認し、解決後にもう一度実行してください。

## トラブルシュート

- `CloudShell environment required`: AWS Consoleで東京リージョンを選び、CloudShellを開き直します。
- account、Region、contextの不一致: STSの利用者、`AWS_REGION`、共通EKSの出力、kubectlの接続先を確認してからやり直します。
- Podが`Pending`: `kubectl describe pod`のEventsでcapacity、taint、affinity、image pullを確認します。
- `CrashLoopBackOff`: 現在と直前のログ、Last State、exit code、restart countを確認します。
- 削除に失敗: 権限、接続先、対象Namespaceを確認し、削除と残存確認をもう一度実行します。

## バージョンと料金

AWS CLIは`2.12.3`以上、`kubectl`はクラスターと同じ、または前後1 minor以内を使います。アプリのimageは`public.ecr.aws/docker/library/busybox:1.36.1`です。料金は[共通EKS基盤README](../common-eks/README.md#cost-warning)のAWS公式リンクから実行直前に確認してください。
