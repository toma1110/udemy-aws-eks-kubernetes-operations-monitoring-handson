# Section 3: Container Insightsとkubectlを照合する

CloudWatch Container Insightsの表示だけで障害を決めつけず、同じRegion、Cluster、Namespace、workload、Pod、UTC時間帯の`kubectl`結果と照合します。このハンズオンでは、データを集める仕組みの不調による「収集欠落」と、PodやNodeで実際に負荷が高い「リソース異常」を分けます。

## できるようになること

- CloudWatchと`kubectl`で、Pod、配置先Node、時刻をそろえて比較できる。
- add-onとAgent Podの状態を先に確認し、収集欠落をリソース異常と誤認しない。
- 収集が健全なときも、単一のグラフだけで断定せず、現在状態を`kubectl`で照合できる。
- 「確認できた事実」「判断」「次に確認すること」を観察メモへ残せる。

## 前提と安全範囲

最初の演習はPython 3.11以上だけで実行でき、AWSアカウントやEKSクラスタは不要です。用意した観察記録は学習用データであり、実環境の実行結果ではありません。

後半の実環境確認は任意です。すでにContainer Insightsが設定されたEKSクラスタと、読み取り権限を持つ環境だけを使います。このSectionではadd-on、Agent、監視設定、workload、Pod、AWSリソースを作成・更新・再起動・削除しません。対象が不明な場合や、読み取り権限がない場合は実行を止めてください。

## 1. AWSを使わずに判断順序を練習する

まずPythonのversionを表示します。この確認は、比較ツールを実行できる環境かを確かめるために行います。

```bash
python --version
```

次に、用意した2つの観察記録を比較し、結果を`observation-result.json`へ保存します。このコマンドの目的は、対象と時刻が一致していること、収集状態が健全か、CloudWatchと`kubectl`の観察が一致するかを同じ順序で確認することです。

```bash
python analyze.py --input fixtures/scenarios.json --output observation-result.json
```

期待する表示:

```text
collection-gap: collection_gap
resource-anomaly: resource_anomaly
PASS: 2 observations written to observation-result.json
```

結果の詳しい内容は`expected-results.json`と一致します。

- `collection-gap`: add-onは`ACTIVE`でも、Agent Podの準備完了数が不足しています。CloudWatchのデータ欠落は、Podのリソース異常ではなく収集経路を先に疑います。
- `resource-anomaly`: add-onとAgent Podが健全で、同じPod・同じ時間帯についてCloudWatchの高CPUと`kubectl`の高CPUが一致しています。リソース異常の調査候補にします。ただし、業務影響や原因までは断定しません。

学習用データと期待結果の対応を検査する場合は、次を実行します。このコマンドの目的は、データの欠落や書き換え、対象・時刻のずれを検出できることを確認することです。

```bash
python -m unittest discover -s tests -v
```

期待結果は、すべてのtestが`ok`となり、最後に`OK`と表示されることです。

## 2. 実環境をread-onlyで確認する（任意）

### 2.1 対象を固定する

次の値を、自分が確認を許可されている対象へ置き換えます。変数に分ける目的は、別のRegion、Cluster、Namespace、workload、Podを混ぜないことです。

```bash
export AWS_REGION="ap-northeast-1"
export CLUSTER_NAME="<cluster-name>"
export NAMESPACE="<namespace>"
export WORKLOAD="<deployment-name>"
export POD_NAME="<pod-name>"
```

`<...>`が一つでも残っている場合は次へ進みません。

現在のKubernetes contextを表示します。この確認の目的は、`kubectl`が意図したClusterへ接続しているかを、コマンド実行前に確かめることです。

```bash
kubectl config current-context
```

表示されたcontextが`CLUSTER_NAME`のクラスタを指すと確認できない場合は停止します。contextを変更するコマンドはこのSectionでは実行しません。

### 2.2 収集状態を確認する

Observability add-onの状態を読み取ります。この確認の目的は、CloudWatchへ送る仕組みがEKS側で利用可能かを確かめることです。

```bash
aws eks describe-addon --region "$AWS_REGION" --cluster-name "$CLUSTER_NAME" --addon-name amazon-cloudwatch-observability --query 'addon.{status:status,version:addonVersion,issues:health.issues}' --output json
```

期待する状態は`status`が`ACTIVE`で、`issues`が空であることです。add-onを使わない既存方式の場合は、管理者が定めた収集構成を確認し、この結果だけで未設定と判断しません。

次に収集用NamespaceのDaemonSetとDeploymentを一覧表示します。この確認の目的は、controller（Agent Podの必要数と状態を管理するKubernetesリソース）の種類と名前を特定することです。

```bash
kubectl get daemonsets,deployments -n amazon-cloudwatch -o wide
```

AgentがDaemonSetで管理されている場合は、一覧で確認したexact nameを使って次を実行します。このコマンドの目的は、各Nodeへ配置すべきAgent数と、現在作成済み・準備完了のAgent数をcontrollerの状態から比較することです。

```bash
kubectl get daemonset <agent-daemonset-name> -n amazon-cloudwatch -o custom-columns=NAME:.metadata.name,DESIRED:.status.desiredNumberScheduled,CURRENT:.status.currentNumberScheduled,READY:.status.numberReady,AVAILABLE:.status.numberAvailable
```

AgentがDeploymentで管理されている場合は、代わりに一覧で確認したexact nameを使って次を実行します。このコマンドの目的は、Deploymentが要求するAgent数と、現在作成済み・準備完了のAgent数を比較することです。

```bash
kubectl get deployment <agent-deployment-name> -n amazon-cloudwatch -o custom-columns=NAME:.metadata.name,DESIRED:.spec.replicas,CURRENT:.status.replicas,READY:.status.readyReplicas,AVAILABLE:.status.availableReplicas
```

表示された方式に合うコマンドを一つだけ使います。controllerが存在しない、名前を特定できない、または別の種類で管理されている場合は推測で名前や種類を補いません。管理者が定めた収集方式を確認し、収集状態は`未確認`と記録します。Pod一覧だけから必要数を決めません。

最後に収集用NamespaceのPodを一覧表示します。この確認の目的は、controllerの不足数を具体的なAgent Podの状態と対応付けることです。

```bash
kubectl get pods -n amazon-cloudwatch -o wide
```

`Pending`、`CrashLoopBackOff`、`ImagePullBackOff`、`Ready`でないPodがある場合は、CloudWatchの欠落値を0や正常値として扱いません。再起動や再インストールは行わず、収集欠落の調査へ切り替えます。

### 2.3 対象とUTC時間帯をそろえる

対象workloadのPodをLabelから一覧表示します。この確認の目的は、CloudWatchで選ぶPodが現在そのworkloadに属し、どのNodeへ配置されているかを確かめることです。

```bash
kubectl get pods -n "$NAMESPACE" -l "app=$WORKLOAD" -o wide
```

環境で別のLabel keyを使う場合は、Deploymentの`.spec.selector.matchLabels`を読み取り、そのLabelへ置き換えます。推測したLabelで別Podを選びません。

対象Podの`.spec.nodeName`を読み取り、配置先Nodeを変数へ保存します。この確認の目的は、Pod viewとNode viewで同じ配置関係をたどることです。

```bash
export NODE_NAME="$(kubectl get pod "$POD_NAME" -n "$NAMESPACE" -o jsonpath='{.spec.nodeName}')"
printf 'POD=%s NODE=%s\n' "$POD_NAME" "$NODE_NAME"
```

`NODE_NAME`が空ならPodはまだNodeへ配置されていません。推測したNodeを選ばず、Podの状態とイベントの確認へ切り替えます。

観察時刻と対象Podの状態を同じ記録へ表示します。この確認の目的は、CloudWatchのグラフへ合わせるUTC時刻と、PodのReady状態・再起動回数を対応付けることです。

```bash
date -u '+%Y-%m-%dT%H:%M:%SZ'; kubectl get pod "$POD_NAME" -n "$NAMESPACE" -o custom-columns=NAME:.metadata.name,READY:.status.containerStatuses[*].ready,RESTARTS:.status.containerStatuses[*].restartCount,PHASE:.status.phase,NODE:.spec.nodeName
```

CloudWatch Consoleで同じ`AWS_REGION`のContainer Insightsを開き、Cluster、Namespace、workload、Podを上記の値へ絞ります。Pod viewで対象Podを確認した後、Node viewで`NODE_NAME`と完全一致するNodeを選びます。時間範囲は、直前に表示したUTC時刻を含む短い固定範囲にします。Pod側だけが高いのか、同じNode上の複数Podも高いのかを比べ、別のNodeや異なる時間帯の値を混ぜません。

現在のCPUとmemoryを読み取ります。この確認の目的は、CloudWatchの異常候補が現在のKubernetes側の観察でも続いているかを補足確認することです。

```bash
kubectl top pod "$POD_NAME" -n "$NAMESPACE"
```

`kubectl top`は現在値であり、CloudWatchの過去グラフそのものではありません。Metrics APIが未設定で失敗しても、それだけでContainer Insightsの収集欠落とは判断しません。時間差が大きい場合は「未照合」と記録します。

配置先Nodeの現在のCPUとmemoryも読み取ります。この確認の目的は、Podだけの負荷候補か、Node全体にも同じ傾向があるかを補足確認することです。

```bash
kubectl top node "$NODE_NAME"
```

Node viewとPod viewは同じ`NODE_NAME`、同じUTC時間範囲で比較します。Node全体の値だけから対象Podを原因と断定しません。

## 3. 判断を観察メモへ残す

次の項目を記録します。値が欠けた場合は空欄にせず「未確認」と書きます。

```text
Region:
Cluster:
Namespace:
workload:
Pod:
Node:
UTC時間範囲:
add-on状態:
Agent controllerの種類／名前:
Agentの必要数／現在数／準備完了数:
CloudWatchで見たPod／Nodeと指標:
kubectlで照合した状態:
判断: 収集欠落 / リソース異常の候補 / 未照合
判断の根拠:
次に確認すること:
```

判断の順序は次のとおりです。

1. Region、Cluster、Namespace、workload、Pod、Node、UTC時間帯が一致しなければ、判断を`未照合`にする。
2. add-onまたはAgent controllerの必要数・現在数・準備完了数が不健全でCloudWatchデータが欠けていれば、`収集欠落`を先に疑う。
3. 収集が健全で、同じ対象・時間帯のCloudWatchと`kubectl`がともに高負荷や再起動増加を示す場合だけ、`リソース異常の候補`にする。
4. 単発値、片方だけの値、時刻のずれでは原因を断定しない。

## 4. 終了時の確認

CloudWatch Consoleで設定したCluster、Namespace、workload、Pod、時間範囲のフィルターを解除します。これは次の調査で古い条件を誤って引き継がないためです。

ローカル演習で作成した結果だけを削除します。Bashでは次のコマンドを使います。このコマンドの目的は、生成した観察結果を消し、配布された学習用データを残すことです。

```bash
rm -- observation-result.json
```

PowerShellの場合は次を使います。同じ目的の別環境向けコマンドなので、どちらか一方だけを実行します。

```powershell
Remove-Item -LiteralPath .\observation-result.json
```

このSectionでadd-on、Agent、監視設定、workload、Pod、AWSリソースを変更していないことを確認します。このSection自体が作るAWSリソースはありません。

以前のSectionなどで共通EKS環境を作成している場合、その環境の料金と削除は`../common-eks/README.md`の別手順に従います。共通環境の削除はこのSectionのフィルター解除やローカルファイル削除とは別であり、対象を特定せずに削除しません。

## Troubleshooting

- CloudWatchに対象が出ない: Region、Cluster、UTC時間範囲、add-on、Agent controller、Agent Podの順に確認します。データがないことをPod正常やCPU 0%と読み替えません。
- CloudWatchと`kubectl`の値が違う: 対象Pod、配置先Node、集計単位、収集間隔、UTC時間帯を確認します。現在値と過去グラフを同じ値として扱いません。
- Agent Podが不健全: 状態とイベントを管理者へ共有し、このSectionでは再起動、add-on更新、権限変更を行いません。
- `Forbidden`または`Unauthorized`: 権限を追加せず、対象Clusterと読み取り権限を管理者へ確認します。
- `kubectl top`が失敗する: Metrics APIの有無を確認し、CloudWatch収集の成否とは分けて記録します。
