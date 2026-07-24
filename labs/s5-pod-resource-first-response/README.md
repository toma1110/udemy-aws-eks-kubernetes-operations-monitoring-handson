# Section 5: Pending / CrashLoopBackOffの初動切り分け

このhands-onの主系統は、`../common-eks/`で作成した短命なEKS基盤に、Section専用namespaceと安全に制限した障害Podを配置して調査することです。固定fixtureはAWSを使えない場合の回帰fallbackであり、実環境の証拠ではありません。

対象lectureは`s5-l3`と`s5-l4`です。Regionは`ap-northeast-1`、cluster/stackは`udemy4-c010-common-20260724`、Section resource prefixは`udemy4-c010-s5-20260724`、namespaceは`udemy4-c010-s5-20260724`です。

public repositoryのrootから、最初にこのdirectoryへ移動します。

```powershell
cd labs/s5-pod-resource-first-response
```

## 目的

1. Pending Podのrequest、Node allocatable、`FailedScheduling` eventを同じ対象で照合する。
2. CrashLoopBackOffの現在/直前log、終了理由、exit code、restart count、eventを照合する。
3. 状態名だけで根本原因を断定せず、観察事実、初動仮説、次のread-only確認を分ける。
4. Section workloadを消してから共通EKS基盤を削除し、残存resourceをfail-closedで確認する。

## 安全設計

- namespace内にPod 3個だけを作ります。hostPath、privileged、hostNetwork、hostPID、DaemonSet、Service、LoadBalancer、PVCは使いません。
- Pending resource scenarioは8 GiBを「request」しますがscheduleされないため、Node memoryを消費しません。
- CrashLoop Podは小さなrequest/limitを持ち、`activeDeadlineSeconds: 600`で最大10分後に停止します。memory scenarioも24 MiB limit内でkillされるためNode全体を枯渇させません。
- loop、CPU stress、disk fill、host操作、Nodeのcordon/drain、scale、IAM変更は行いません。
- 最大6時間の共通基盤期限とは別に、Section workloadは観察後すぐ削除します。

## 1. 共通基盤を作る

`../common-eks/README.md`のpreflight、作成、status確認を先に完了します。`API_PUBLIC_ACCESS_CIDR`には自分のexact CIDRを設定し、`0.0.0.0/0`を使いません。

```powershell
cd ../common-eks
$env:AWS_ACCOUNT_ID = "<exact-12-digit-account-id>"
$env:API_PUBLIC_ACCESS_CIDR = "<trusted-public-ip>/32"
$env:AVAILABILITY_ZONE_A = "ap-northeast-1a"
$env:AVAILABILITY_ZONE_B = "ap-northeast-1c"
$env:CLEANUP_DEADLINE_UTC = [DateTimeOffset]::UtcNow.AddHours(4).ToString("yyyy-MM-dd'T'HH:mm:ss'Z'", [Globalization.CultureInfo]::InvariantCulture)
./scripts/preflight.ps1
./scripts/create.ps1
./scripts/status.ps1
cd ../s5-pod-resource-first-response
```

期待結果: clusterが`ACTIVE`、1台の`t3.medium` nodeが`Ready`です。

`AWS_ACCOUNT_ID`はs5のapply/capture/cleanupでも必須です。各scriptはSTS account、固定Region、stack ARN/tag/output、EKS cluster ARN/tagを再照合し、現在contextがexact cluster ARNと完全一致しなければ停止します。自動cleanup scheduleが期限にstackを削除するため、期限後にSection scriptを実行できないのは期待されるfail-closed動作です。

## 2. Section scenarioを作る

scriptは現在contextがexact cluster名を含むことを確認してから、固定manifestを順番にapplyします。

```powershell
./scripts/apply-scenarios.ps1
kubectl get pods -n udemy4-c010-s5-20260724 -o wide
```

数分以内の期待状態:

- `udemy4-c010-s5-20260724-pending-capacity`: `Pending`
- `udemy4-c010-s5-20260724-crashloop-app`: `CrashLoopBackOff`
- `udemy4-c010-s5-20260724-crashloop-memory`: restart後に`CrashLoopBackOff`（直前終了理由は`OOMKilled`が期待値）

image pullやbackoff timingにより一時状態は異なります。状態が見えるまで無制限に待たず、10分で打ち切ります。

## 3. read-onlyで調査して証拠を保存する

次のscriptは`get`、`describe`、`logs`だけを使い、`$env:TEMP/udemy4-c010-s5-20260724-evidence`へ保存します。Kubernetes Secret、AWS account ID、credentialは取得しません。

```powershell
./scripts/capture-evidence.ps1
```

scriptと同じread-only commandは次です。

```powershell
kubectl get pods -n udemy4-c010-s5-20260724 -o wide
kubectl get events -n udemy4-c010-s5-20260724 --sort-by=.lastTimestamp
kubectl describe pod udemy4-c010-s5-20260724-pending-capacity -n udemy4-c010-s5-20260724
kubectl describe pod udemy4-c010-s5-20260724-crashloop-app -n udemy4-c010-s5-20260724
kubectl logs udemy4-c010-s5-20260724-crashloop-app -n udemy4-c010-s5-20260724 --tail=100
kubectl logs udemy4-c010-s5-20260724-crashloop-app -n udemy4-c010-s5-20260724 --previous --tail=100
kubectl describe pod udemy4-c010-s5-20260724-crashloop-memory -n udemy4-c010-s5-20260724
kubectl logs udemy4-c010-s5-20260724-crashloop-memory -n udemy4-c010-s5-20260724 --previous --tail=100
kubectl get nodes -o custom-columns=NAME:.metadata.name,ALLOCATABLE_MEMORY:.status.allocatable.memory
```

Pendingでは8 GiB requestとNode allocatable、同じPodの`FailedScheduling`を照合します。CrashLoopでは同じPod/containerの直前log、`lastState.terminated.reason`、exit code、restart count、BackOff eventを照合します。`CrashLoopBackOff`だけを根拠にOOMやapplication defectを断定しません。

## 4. Section cleanup

共通stackより先に、固定namespaceだけを削除します。

```powershell
./scripts/cleanup-section.ps1
```

scriptがnamespaceの消失を確認できない場合、共通基盤の削除へ進みません。

## 5. 共通cleanup

```powershell
cd ../common-eks
./scripts/delete.ps1
```

stack、cluster、exact tag付きEC2/EBS/ENI、cluster prefixのCloudWatch log groupが残ればscriptは失敗し、外部guardを保持します。全query成功かつ残存なしの場合だけexact guard stackを削除し、guard stack/schedule/roleの消失まで確認します。wildcard deleteは行いません。

## 費用

Section manifest自体は追加のLoad Balancer、NAT Gateway、EBS、CloudWatchを作りません。費用は主に共通EKS基盤の稼働時間です。現行単価、約USD 0.97/6時間のparameterized estimate、変動要因は`../common-eks/README.md`を参照してください。実請求は必ず直前に公式pricingで再確認します。

## fixture回帰fallback

AWSを使えない場合だけ、fixture analyzerで調査順序を練習できます。

```powershell
python -B analyze.py --check
python -B -m unittest discover -s tests -v
```

Pythonがbytecode cacheを作らない隔離環境では、同じ検査を`python analyze.py --check`として実行しても結果は同じです。

fixtureは合成データであり、EKSの作成、Pod状態、AWS Console、CloudWatch、IAM、networkのlive動作を証明しません。

### Route A: 既存EKSクラスタを読み取り専用で調べる

共通基盤を作成できないが、調査を許可された既存clusterがある場合の任意routeです。権限やデータがないことは演習の失敗ではありません。その場合は`Route B: fixtureで決定的に調べる`へ進みます。targetを確定してから次のplaceholderを置き換えます。

```powershell
kubectl config current-context
kubectl config get-contexts
kubectl --context <context> get pods -n <namespace> -o wide
kubectl --context <context> describe pod <pod> -n <namespace>
kubectl --context <context> logs <pod> -n <namespace> --previous --tail=100
kubectl --context <context> get events -n <namespace> --sort-by=.lastTimestamp
```

IAMとKubernetes RBACの両方を既に持つ対象だけを読みます。権限はこの演習で変更しません。Container Insightsが未設定ならCloudWatchの欠測を原因と断定しません。

- [View Kubernetes resources in the AWS Management Console](https://docs.aws.amazon.com/eks/latest/userguide/view-kubernetes-resources.html)
- [EKS Container Insights metrics](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/Container-Insights-metrics-EKS.html)

この任意Route Aの読み取り手順そのものによる新規リソース費用は発生しません。ただし既存cluster、workload、CloudWatch設定には既存料金があり得ます。既存resourceを教材cleanupの対象にしないため、クラウド側のクリーンアップはありません。

### Route B: fixtureで決定的に調べる

前述の`python -B analyze.py --check`を実行します。

## Troubleshooting

- `Forbidden` / `Unauthorized`: IAMやKubernetes accessをこのlab内で変更せず、管理者へ確認します。
- nodeが`Ready`にならない: CloudFormation events、node group status、public subnet routeとpublic IPv4、API CIDRを確認します。
- `ImagePullBackOff`: public ECRへのoutbound到達性とimage名を確認します。別imageへの場当たり的置換はしません。
- Pendingにならない: Pod requestとNode allocatable、eventを保存し、manifestが変更されていないか確認します。
- CrashLoopが見えない: `activeDeadlineSeconds`経過後ならcleanupして再applyできます。期限を削除して無制限loopにしません。
