# Section 5: Pending / CrashLoopBackOffの初動切り分け

このハンズオンでは、コース共通のCloudFormationテンプレートで作成したEKSクラスタを使います。AWS Management ConsoleとAWS CloudShellから、Podが起動しない原因と再起動を繰り返す原因を順番に調べます。

ハンズオンURL:
https://github.com/toma1110/udemy-aws-eks-kubernetes-operations-monitoring-handson/tree/main/labs/s5-pod-resource-first-response

## 学習目標

1. Pending Podのrequest、Nodeの空き容量、`FailedScheduling` eventを確認する。
2. CrashLoopBackOffのlog、終了理由、exit code、restart countを確認する。
3. 状態名だけで原因を決めず、確認できた事実から次の確認項目を選ぶ。
4. Section 5で作成したPodを削除してから、共通EKS環境を削除する。

## 前提

- 自分で利用を許可されたAWSアカウントを使います。
- AWS Management Consoleで東京リージョン `ap-northeast-1` を選びます。
- コマンドはすべてAWS CloudShellのBashで実行します。
- 共通EKS環境の作成から削除まで、続けて作業できる時間を確保します。
- `AWS_ACCOUNT_ID`には、これから使う12桁のAWSアカウントIDを設定します。

この演習では、namespace内にPodを3個だけ作成します。Load Balancer、NAT Gateway、PVCは作成せず、Nodeの設定やIAM権限も変更しません。CrashLoopBackOffを確認するPodは10分で停止します。

## 1. CloudShellを開く

AWS Management Console上部の検索欄に `CloudShell` と入力し、検索結果の「CloudShell」を選択します。東京リージョン `ap-northeast-1` が選ばれていることを確認してください。

CloudShellが開いたら、次を実行します。

```bash
export AWS_REGION="ap-northeast-1"
export AWS_DEFAULT_REGION="ap-northeast-1"
aws --version
kubectl version --client --output=json
aws sts get-caller-identity --region "$AWS_REGION" --no-cli-pager
printf 'HOME=%s\n' "$HOME"
df -h "$HOME"
```

期待結果:

- AWS CLIとkubectlのversionが表示される。
- `aws sts get-caller-identity`に、自分が利用するAWSアカウントが表示される。
- CloudShellの`$HOME`に空き容量がある。CloudShellの永続領域はRegionごとに1 GBです。

表示されたAWSアカウントが利用予定のアカウントと異なる場合は、ここで停止してください。

続けて、教材リポジトリをCloudShellの`$HOME`へ準備します。既に同じ名前のdirectoryがある場合は、正しいGit repositoryで変更中のfileがないことを確認してからfast-forwardします。別のdirectoryや変更中のfileを上書きしません。

```bash
export HANDSON_REPO="$HOME/udemy-aws-eks-kubernetes-operations-monitoring-handson"
export HANDSON_URL="https://github.com/toma1110/udemy-aws-eks-kubernetes-operations-monitoring-handson.git"

if [[ -e "$HANDSON_REPO" ]]; then
  [[ -d "$HANDSON_REPO/.git" ]] || {
    echo "同名のdirectoryがGit repositoryではありません。名前を変更してから再実行してください。" >&2
    exit 1
  }
  [[ "$(git -C "$HANDSON_REPO" remote get-url origin)" == "$HANDSON_URL" ]] || {
    echo "既存repositoryのoriginが教材URLと異なります。" >&2
    exit 1
  }
  [[ -z "$(git -C "$HANDSON_REPO" status --porcelain)" ]] || {
    echo "既存repositoryに変更中のfileがあります。保存または取り消してから再実行してください。" >&2
    exit 1
  }
  git -C "$HANDSON_REPO" pull --ff-only
else
  git clone "$HANDSON_URL" "$HANDSON_REPO"
fi

cd "$HANDSON_REPO/labs/s5-pod-resource-first-response"
```

## 2. 共通EKS環境を作る

Section 5のdirectoryから、共通EKS環境の手順へ移動します。

```bash
cd ../common-eks
export COMMON_EKS_DIR="$(pwd)"
export AWS_ACCOUNT_ID="<12桁のAWSアカウントID>"
export API_PUBLIC_ACCESS_CIDR="<現在のCloudShellのパブリックIP>/32"
export AVAILABILITY_ZONE_A="ap-northeast-1a"
export AVAILABILITY_ZONE_B="ap-northeast-1c"
export CLEANUP_DEADLINE_UTC="$(date -u -d '+4 hours' '+%Y-%m-%dT%H:%M:%SZ')"
chmod +x "$COMMON_EKS_DIR"/scripts/*.sh
"$COMMON_EKS_DIR/scripts/preflight.sh"
"$COMMON_EKS_DIR/scripts/create.sh"
"$COMMON_EKS_DIR/scripts/status.sh"
```

`API_PUBLIC_ACCESS_CIDR`には自分の現在のIPアドレスを `/32` で指定し、`0.0.0.0/0`は使いません。詳しい入力値、費用、作成状況の確認は`../common-eks/README.md`に従ってください。

期待結果:

- EKSクラスタが`ACTIVE`になる。
- 1台の`t3.medium` Nodeが`Ready`になる。

## 3. Section 5のPodを作る

```bash
cd ../s5-pod-resource-first-response
export S5_DIR="$(pwd)"
chmod +x "$S5_DIR"/scripts/*.sh
export EVIDENCE_DIR="$HOME/udemy4-c010-s5-20260724-evidence"
mkdir -p -- "$EVIDENCE_DIR"
"$S5_DIR/scripts/apply-scenarios.sh"
kubectl get pods -n udemy4-c010-s5-20260724 -o wide
```

数分以内の期待状態:

- `udemy4-c010-s5-20260724-pending-capacity`: `Pending`
- `udemy4-c010-s5-20260724-crashloop-app`: `CrashLoopBackOff`
- `udemy4-c010-s5-20260724-crashloop-memory`: 再起動後に`CrashLoopBackOff`

image pullや再起動のタイミングにより、一時的な表示は異なります。10分以上待ち続けず、次の調査へ進みます。

## 4. Pendingを調べる

```bash
kubectl describe pod udemy4-c010-s5-20260724-pending-capacity -n udemy4-c010-s5-20260724
kubectl get events -n udemy4-c010-s5-20260724 --sort-by=.lastTimestamp
kubectl get nodes -o custom-columns=NAME:.metadata.name,ALLOCATABLE_MEMORY:.status.allocatable.memory
```

確認する場所:

- Podが要求するmemoryは`8Gi`か。
- eventに`FailedScheduling`があるか。
- Nodeの`ALLOCATABLE_MEMORY`はPodのrequestを満たせるか。

このPodはscheduleされないため、Node上で8 GiBのmemoryを消費しません。

## 5. CrashLoopBackOffを調べる

```bash
kubectl describe pod udemy4-c010-s5-20260724-crashloop-app -n udemy4-c010-s5-20260724
kubectl logs udemy4-c010-s5-20260724-crashloop-app -n udemy4-c010-s5-20260724 --tail=100
kubectl logs udemy4-c010-s5-20260724-crashloop-app -n udemy4-c010-s5-20260724 --previous --tail=100

kubectl describe pod udemy4-c010-s5-20260724-crashloop-memory -n udemy4-c010-s5-20260724
kubectl logs udemy4-c010-s5-20260724-crashloop-memory -n udemy4-c010-s5-20260724 --previous --tail=100
```

確認する場所:

- 現在と直前のlogに何が記録されているか。
- `Last State`の`Reason`と`Exit Code`は何か。
- `Restart Count`は増えているか。
- memory用Podの直前終了理由は`OOMKilled`か。

`CrashLoopBackOff`という表示だけで、memory不足やapplicationの不具合と決めつけないでください。log、終了理由、limit、eventを組み合わせて判断します。

調査結果をまとめて保存する場合は、次を実行します。このscriptは`get`、`describe`、`logs`だけを使用します。

```bash
"$S5_DIR/scripts/capture-evidence.sh"
df -h "$HOME"
```

## 6. Section 5のPodを削除する

```bash
"$S5_DIR/scripts/cleanup-section.sh"
```

namespaceの削除確認に失敗した場合は、共通EKS環境の削除へ進まないでください。

## 7. 共通EKS環境を削除する

```bash
"$COMMON_EKS_DIR/scripts/delete.sh"
```

期待結果:

- Section 5のnamespaceが存在しない。
- CloudFormation stackとEKSクラスタが存在しない。
- この演習で作成したEC2、EBS、ENI、CloudWatch Logsが残っていない。

削除scriptが残存リソースを検出した場合は、表示された対象を確認し、削除完了までAWS Management Consoleを閉じないでください。

## 費用

Section 5のPodは、追加のLoad Balancer、NAT Gateway、EBS、CloudWatch Logsを作りません。費用は主に共通EKS環境の稼働時間です。約USD 0.97/6時間の概算と変動要因は`../common-eks/README.md`を参照し、実請求に使われる最新料金は作成直前にAWS公式ページで確認してください。

## Troubleshooting

- `Forbidden` / `Unauthorized`: この演習内でIAMやKubernetesの権限を変更せず、管理者へ確認します。
- Nodeが`Ready`にならない: CloudFormation events、Node group status、public subnet route、public IPv4、API CIDRを確認します。
- `ImagePullBackOff`: public ECRへの接続とimage名を確認します。別imageへ置き換えません。
- Pendingにならない: Pod request、Node allocatable、eventを保存し、manifestが変更されていないか確認します。
- CrashLoopBackOffが見えない: 10分経過後はSection 5のPodを削除し、もう一度作成します。停止時間を削除して無制限に実行しないでください。

参考:

- [EKSリソースをAWS Management Consoleで表示する](https://docs.aws.amazon.com/eks/latest/userguide/view-kubernetes-resources.html)
- [EKSのContainer Insights metrics](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/Container-Insights-metrics-EKS.html)
