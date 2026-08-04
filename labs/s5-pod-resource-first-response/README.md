# Section 5: Pending / CrashLoopBackOffの初動切り分け

このハンズオンでは、コース共通のCloudFormationテンプレートで作成したEKSクラスタを使います。AWS Management ConsoleとAWS CloudShellから、PodがNodeへ配置されず待機する`Pending`と、起動後すぐに終了して再起動を繰り返す`CrashLoopBackOff`を調べます。状態名だけで原因を決めず、Podの設定、Nodeの空き容量、Kubernetesのイベント、直前のログを結び付けて、次の安全な確認先を選びます。

ハンズオンURL:
https://github.com/toma1110/udemy-aws-eks-kubernetes-operations-monitoring-handson/tree/main/labs/s5-pod-resource-first-response

## 学習目標

1. Pending Podが要求するメモリ量、Nodeが割り当てられるメモリ量、配置失敗を示す`FailedScheduling`イベントを確認する。
2. CrashLoopBackOffの現在と直前のログ、終了理由、終了コード、再起動回数を確認する。
3. 状態名だけで原因を決めず、確認できた事実から次の確認項目を選ぶ。
4. Section 5で作成したPodを削除してから、共通EKS環境を削除する。

## 前提

- AWS Management Consoleで東京リージョン `ap-northeast-1` を選びます。
- コマンドはすべてAWS CloudShellのBashで実行します。
- 共通EKS環境の作成から削除まで、続けて作業できる時間を確保します。

この演習では、専用のnamespace（Kubernetes内でリソースを分ける単位）にPodを3個だけ作成します。Load Balancer、NAT Gateway、PVCは作成せず、Nodeの設定やIAM権限も変更しません。CrashLoopBackOffを確認するPodは10分で停止します。

## AWSを使わずに確認順序を練習する

用意されたfixture（確認結果のサンプル）を分析し、PendingとCrashLoopBackOffでどの情報を先に確認するかを、AWSアカウントやKubernetesクラスタなしで練習できます。このディレクトリでPython 3.11以上を使って実行します。

```bash
python analyze.py --check
```

期待する表示は`PASS: fixtures and analysis match expected-results.json`です。Pythonのversionに関するエラーが出た場合は`python --version`で3.11以上か確認します。fixtureや期待結果の不一致が表示された場合は、`fixtures/`と`expected-results.json`を同じ取得時点のファイルへ戻してから再実行し、内容を自己判断で書き換えないでください。

## 1. CloudShellを開く

AWS Management Console上部の検索欄に `CloudShell` と入力し、検索結果の「CloudShell」を選択します。東京リージョン `ap-northeast-1` が選ばれていることを確認してください。

CloudShellが開いたら、次を実行します。

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
- CloudShellの`$HOME`に空き容量がある。CloudShellの永続領域はRegionごとに1 GBです。

続けて、教材リポジトリをCloudShellの`$HOME`へ準備します。すでに同じ名前のフォルダがある場合は、教材のGitリポジトリであり、変更中のファイルがないことを確認してから最新版へ更新します。別のフォルダや変更中のファイルは上書きしません。

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

Section 5のフォルダから、共通EKS環境の手順へ移動します。ここでは演習対象のクラスタとNodeを用意し、Podを配置できる状態まで確認します。

```bash
cd ../common-eks
export COMMON_EKS_DIR="$(pwd)"
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

ここでは原因が異なる3つのPodを専用namespaceへ作ります。作成直後の一覧は、どのPodが待機し、どのPodが再起動しているかを見分けるために使います。

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

まずPodの詳細とイベントで「なぜ配置されなかったか」を確認し、次にNode側の割り当て可能なメモリ量と比べます。Node増強やPod変更はまだ行いません。

```bash
kubectl describe pod udemy4-c010-s5-20260724-pending-capacity -n udemy4-c010-s5-20260724
kubectl get events -n udemy4-c010-s5-20260724 --sort-by=.lastTimestamp
kubectl get nodes -o custom-columns=NAME:.metadata.name,ALLOCATABLE_MEMORY:.status.allocatable.memory
```

確認する場所:

- Podが要求するメモリ量は`8Gi`か。
- イベントに、配置できなかったことを示す`FailedScheduling`があるか。
- Nodeの`ALLOCATABLE_MEMORY`（Podへ割り当てられるメモリ量）は、Podの要求量を満たせるか。

期待結果は、`FailedScheduling`とメモリ不足を示すメッセージがあり、PodがNodeへ配置されていないことです。このPodは配置されないため、Node上で8 GiBのメモリを消費しません。この結果なら、最初の原因候補は「Podの要求量が現在のNode容量を超えている」です。

## 5. CrashLoopBackOffを調べる

次に、アプリケーションの終了とメモリ上限超過を見分けます。`--previous`は、再起動前のコンテナが残したログを読むための指定です。

```bash
kubectl describe pod udemy4-c010-s5-20260724-crashloop-app -n udemy4-c010-s5-20260724
kubectl logs udemy4-c010-s5-20260724-crashloop-app -n udemy4-c010-s5-20260724 --tail=100
kubectl logs udemy4-c010-s5-20260724-crashloop-app -n udemy4-c010-s5-20260724 --previous --tail=100

kubectl describe pod udemy4-c010-s5-20260724-crashloop-memory -n udemy4-c010-s5-20260724
kubectl logs udemy4-c010-s5-20260724-crashloop-memory -n udemy4-c010-s5-20260724 --previous --tail=100
```

確認する場所:

- 現在と直前のログに何が記録されているか。
- `Last State`の`Reason`と`Exit Code`は何か。
- `Restart Count`は増えているか。
- メモリ上限を試すPodの直前終了理由は`OOMKilled`か。

期待結果は、アプリケーション用Podでは終了コード`42`と意図的な終了を示すログ、メモリ用Podでは`OOMKilled`を確認できることです。`CrashLoopBackOff`という表示だけでメモリ不足やアプリケーション不具合と決めつけず、ログ、終了理由、メモリ上限、イベントを組み合わせて判断します。

調査結果をまとめて保存する場合は、次を実行します。このスクリプトは状態を取得する`get`、`describe`、`logs`だけを使用し、Podや設定を変更しません。

```bash
"$S5_DIR/scripts/capture-evidence.sh"
df -h "$HOME"
```

## 6. Section 5のPodを削除する

Section 5で作成した専用namespaceだけを削除します。スクリプトは対象を確認してから削除し、namespaceが残っていないことまで検査します。

```bash
"$S5_DIR/scripts/cleanup-section.sh"
```

namespaceの削除確認に失敗した場合は、共通EKS環境の削除へ進まないでください。

期待結果は`Section namespace cleanup verified.`です。この表示がなければ、エラーに示されたnamespaceを確認してから再実行します。

## 7. 共通EKS環境を削除する

Section 5のnamespaceが消えたことを確認できたら、課金の中心となる共通EKS環境を削除します。

```bash
"$COMMON_EKS_DIR/scripts/delete.sh"
```

期待結果:

- Section 5のnamespaceが存在しない。
- CloudFormation stackとEKSクラスタが存在しない。
- この演習で作成したEC2、EBS、ENI、CloudWatch Logsが残っていない。

削除スクリプトが残存リソースを検出した場合は、表示された対象を確認し、削除完了までAWS Management Consoleを閉じないでください。Section 5のnamespace、CloudFormation stack、EKSクラスタ、関連するEC2、EBS、ENI、CloudWatch Logsのいずれかが残っている間は、cleanup完了と判断しません。

## 費用

Section 5のPodは、追加のLoad Balancer、NAT Gateway、EBS、CloudWatch Logsを作りません。費用は主に共通EKS環境の稼働時間です。約USD 0.97/6時間の概算と変動要因は`../common-eks/README.md`を参照し、実請求に使われる最新料金は作成直前にAWS公式ページで確認してください。

## Troubleshooting

- `Forbidden` / `Unauthorized`: この演習内でIAMやKubernetesの権限を変更せず、管理者へ確認します。
- Nodeが`Ready`にならない: CloudFormationイベント、Node groupの状態、public subnetの経路、public IPv4、API CIDRを確認します。
- `ImagePullBackOff`: public ECRへの接続とimage名を確認します。別imageへ置き換えません。
- Pendingにならない: Podの要求量、Nodeの割り当て可能量、イベントを保存し、manifestが変更されていないか確認します。
- CrashLoopBackOffが見えない: 10分経過後はSection 5のPodを削除し、もう一度作成します。停止時間を削除して無制限に実行しないでください。

参考:

- [EKSリソースをAWS Management Consoleで表示する](https://docs.aws.amazon.com/eks/latest/userguide/view-kubernetes-resources.html)
- [EKSのContainer Insights metrics](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/Container-Insights-metrics-EKS.html)
