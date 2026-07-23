# Pod リソース問題の初動切り分け

この演習は、既存の EKS クラスタを読み取り専用で調べる live route と、固定済み合成データをローカルで調べる fixture route の2経路で行います。

- Primary: 既存クラスタと参照権限がある場合は live route
- Fallback: クラスタがない、対象 Pod がない、IAM/RBAC 権限がない、Container Insights が未設定、またはメトリクスがない場合は fixture route

権限やデータがないことは演習の失敗ではありません。live routeで確認できた範囲を記録してfixture routeへ進めば、演習を完了できます。

## 目的

- context、namespace、対象 Pod を確認してから読み取り専用調査を始める
- Pending の event から、容量不足、taint/toleration、nodeSelector/affinity のどこを次に確認するか選ぶ
- CrashLoopBackOff で現在ログだけでなく、直前コンテナのログ、前回終了理由、exit code、event、probe情報を照合する
- EKS Console、CloudWatch Container Insights、`kubectl`の情報を、同じ対象に結び付けて読む
- 証拠がない原因を推測で追加せず、観察事実、初動仮説、次の確認を分けて記録する

## 安全境界

この演習は調査だけです。AWSリソースやKubernetesリソースを作成、更新、再起動、scale、削除しません。`kubectl apply`、`create`、`edit`、`patch`、`set`、`scale`、`rollout restart`、`delete`は実行しません。権限不足を見つけても、この演習内でIAM、EKS access entry、Role、RoleBinding、ClusterRoleBindingを変更しません。

live routeでは自分が参照を許可された既存クラスタとnamespaceだけを使い、機密情報を出力ファイルや提出物へ保存しないでください。本番の修正判断は、この演習の初動仮説だけでは行いません。

## 前提条件

### live route

- 自分が参照を許可された既存EKSクラスタ
- AWS Consoleで対象Regionとクラスタを参照できるIAM権限
- 対象クラスタへ接続済みの`kubectl`
- 対象resourceを`get`、`list`、`watch`相当で参照し、Podの`describe`、`logs`、eventsを確認できるKubernetes RBAC

EKS ConsoleのResources tabとCompute tabのNodes表示には、AWS側のIAM権限（`eks:AccessKubernetesApi`など）と、クラスタ側のKubernetes RBACの両方が必要です。片方だけでは表示できません。権限の付与や変更は管理者の作業であり、この演習には含めません。

### fixture route

- Python 3.11以上（標準ライブラリだけを使用）
- PowerShell
- AWSアカウント、AWS CLI、`kubectl`、Kubernetesクラスタは不要

`fixtures/`はKubernetes APIの代表的な情報を学習用に単純化した合成データです。実環境の完全なAPI応答ではありません。

## Route A: 既存EKSクラスタを読み取り専用で調べる

### 1. 対象を固定する

最初にAWS ConsoleのRegion selectorで対象クラスタのRegionを選びます。クラスタ名、namespace、Pod名を自分の作業メモに記録します。教材や共有ログにはAWS account IDを記録しません。

PowerShellで現在のcontextと利用可能なcontextを確認します。

```powershell
kubectl config current-context
kubectl config get-contexts
```

次のコマンドでは`<context>`、`<namespace>`、`<pod>`を自分が参照を許可された対象へ置き換えます。contextやnamespaceが確定しない場合は実行を止め、fixture routeへ進みます。

```powershell
kubectl --context <context> get namespaces
kubectl --context <context> get pods -n <namespace> -o wide
kubectl --context <context> get nodes -o wide
```

期待結果は「コマンドが成功し、許可された範囲が表示される」ことだけです。Pending、CrashLoopBackOff、NotReadyが存在するとは限りません。`Forbidden`、`Unauthorized`、空の一覧も、環境状態または権限を示す観察結果であり、演習失敗ではありません。

### 2. EKS Consoleで同じ対象を見る

1. AWS ConsoleでAmazon EKSを開き、対象Regionを確認します。
2. `Clusters`から対象クラスタを選びます。
3. `Resources` tabでresource group（例: `Workloads`）を選び、`Pods`またはPodを管理するworkloadを開きます。
4. 対象Podが表示される場合は、namespace、状態、Node、再起動に関する表示を`kubectl`の対象と照合します。
5. Nodeは`Resources` → `Cluster` → `Nodes`、またはclusterの`Compute` tab → `Nodes`で確認します。

Resources tabやCompute tabのNodesが表示されない場合は、IAMとKubernetes RBACの両方が満たされているかを管理者へ確認します。この演習では権限を変更せず、fixture routeへ進みます。AWS公式手順: [View Kubernetes resources in the AWS Management Console](https://docs.aws.amazon.com/eks/latest/userguide/view-kubernetes-resources.html)

### 3. Pendingを深掘りする

対象namespaceにPending Podがある場合だけ、同じPodを次のコマンドで確認します。

```powershell
kubectl --context <context> describe pod <pod> -n <namespace>
kubectl --context <context> get events -n <namespace> --field-selector involvedObject.kind=Pod,involvedObject.name=<pod> --sort-by=.lastTimestamp
kubectl --context <context> describe node <node>
```

`<node>`はPodやeventで確認した対象Nodeへ置き換えます。未スケジュールのPodにはNodeが割り当てられていないことがあります。その場合はNodeの`describe`を無理に実行せず、`FailedScheduling` eventと、参照を許可されたNode一覧から確認を始めます。

記録するのは、同じPodに結び付くscheduler event、resource requests、taint/toleration、nodeSelector/affinity、Node label/allocatableです。これらの証拠がなければ、容量不足、taint、affinityを原因と断定しません。

### 4. CrashLoopBackOffを深掘りする

対象namespaceにCrashLoopBackOff Podがある場合だけ、同じPodを確認します。

```powershell
kubectl --context <context> describe pod <pod> -n <namespace>
kubectl --context <context> logs <pod> -n <namespace> --tail=100
kubectl --context <context> logs <pod> -n <namespace> --previous --tail=100
kubectl --context <context> get events -n <namespace> --field-selector involvedObject.kind=Pod,involvedObject.name=<pod> --sort-by=.lastTimestamp
```

複数containerのPodでは、対象containerを確認して各`logs`コマンドへ`-c <container>`を追加します。`--previous`が「previous terminated container not found」相当になる場合は、直前containerのログが保持されていないという観察結果です。別Podのログで代用しません。

前回終了理由、exit code、restart count、現在ログ、`--previous`ログ、BackOff/Unhealthy event、probe設定を同じPod・containerで照合します。CrashLoopBackOffという状態名だけでOOMやアプリケーション不具合を断定しません。

### 5. Container Insightsを使える場合だけ照合する

CloudWatch Consoleで対象Regionを確認し、`Insights` → `Container Insights`を開きます。画面で対象cluster、namespace、workload、PodまたはNodeを選べる場合は、`kubectl`と同じ対象・時間帯を選びます。PodのCPU/memoryやrestart、NodeのCPU/memoryなど、利用可能な表示だけを観察します。

Container Insightsのメトリクスは`ContainerInsights` namespaceへ発行されます。設定が完了する前はメトリクスが表示されません。Container Insightsが未設定、対象が選べない、データがない、または参照権限がない場合は、欠落を障害原因と断定せずfixture routeへ進みます。設定、add-on導入、agent変更、alarm/dashboard作成はこの演習では行いません。AWS公式メトリクス一覧: [Amazon EKS and Kubernetes Container Insights metrics](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/Container-Insights-metrics-EKS.html)

### 6. live観察をまとめる

次の4項目だけを、自分の許可された作業場所へ記録します。

1. 対象: Region、cluster、namespace、Pod/Node（account IDは記録しない）
2. 観察事実: 実際に表示された状態、event、終了理由、ログ、メトリクス
3. 初動仮説: 観察事実から説明できる範囲
4. 次の読み取り確認: 仮説を検証するために追加で読む対象

問題状態のPodがない、または権限・データがない場合は「live結果なし」と記録し、fixture routeで決定的なシナリオを完了します。

## Route B: fixtureで決定的に調べる

### 1. このディレクトリへ移動する

```powershell
cd labs/s5-pod-resource-first-response
```

### 2. PodとNodeの一覧を確認する

```powershell
Get-Content fixtures/get-pods.json
Get-Content fixtures/get-nodes.json
```

期待結果: `training` namespaceに3つのPending Podと3つのCrashLoopBackOff Podがあります。2台のNodeはどちらもReadyであり、Node全体停止だけを原因候補にしないことが分かります。

### 3. 3種類のPendingを照合する

```powershell
Get-Content fixtures/describe-pending-capacity.json
Get-Content fixtures/describe-pending-taint.json
Get-Content fixtures/describe-pending-affinity.json
Get-Content fixtures/events.json
```

期待結果:

- `pending-capacity`: memory request `5Gi`と、同じPodの`Insufficient memory` event
- `pending-taint`: tolerationなしと、同じPodのuntolerated `dedicated=ops:NoSchedule` taint event
- `pending-affinity`: `workload=gpu` selector、`zone=ap-northeast-1c` required affinity、同じPodのselector/affinity不一致event

### 4. 3種類のCrashLoopBackOffを照合する

```powershell
Get-Content fixtures/describe-crashloop-app.json
Get-Content fixtures/logs-crashloop-app-previous.txt
Get-Content fixtures/describe-crashloop-oom.json
Get-Content fixtures/logs-crashloop-oom-previous.txt
Get-Content fixtures/describe-crashloop-probe.json
Get-Content fixtures/logs-crashloop-probe-previous.txt
Get-Content fixtures/events.json
```

期待結果:

- `crashloop-app`: 前回理由`Error`、exit code `1`、`APP_MODE`欠落の前回ログ、同じPodのBackOff event
- `crashloop-oom`: 前回理由`OOMKilled`、exit code `137`、memory limit `256Mi`、同じPodのBackOff event
- `crashloop-probe`: `/healthz`、HTTP 500のUnhealthy event、前回理由`Error`、exit code `143`

### 5. 固定データと期待結果を検証する

```powershell
python analyze.py --check
```

期待結果: `PASS: fixtures and analysis match expected-results.json`と表示され、終了コードは0です。

### 6. 単体テストを実行する

```powershell
python -m unittest discover -s tests -v
```

期待結果: すべてのテストが`ok`になり、最後に`OK`と表示されます。

## 診断結果の読み方

どちらのrouteでも結論は初動仮説であり、根本原因の確定ではありません。Pendingはschedulerの`FailedScheduling` eventとPod/Nodeの条件を組み合わせます。CrashLoopBackOffは再起動待ちという表示だけで原因を決めず、前回ログ、前回終了理由とexit code、event、probe設定を対象ごとに照合します。

fixtureにはPVC未bindingやimage pull失敗を示す証拠がありません。それらをfixtureの診断結果へ追加しません。live routeでも、`FailedMount`、未binding PVC、`ErrImagePull`、`ImagePullBackOff`など対象固有の証拠が出た場合に限り追加調査します。

## トラブルシューティング

| 症状 | 確認すること |
| --- | --- |
| EKS clusterが一覧にない | RegionとIAMの参照範囲を確認する。既存clusterがなければfixture routeへ進む |
| Resources/ComputeのNodeが見えない | IAMのEKS参照権限とKubernetes RBACの両方を管理者へ確認する。演習内で変更しない |
| `Forbidden`または`Unauthorized` | context、認証、namespace、RBAC範囲を確認する。権限を自己変更せずfixture routeへ進む |
| Podやeventが空 | 対象namespace、Pod名、event保持期間を確認する。問題Podがなければfixture routeへ進む |
| `--previous`ログがない | 直前containerがない、またはログが保持されていない可能性を記録し、別Podで代用しない |
| Container Insightsが空 | Region、cluster selector、設定状態、時間範囲、参照権限を確認する。設定変更せずfixture routeへ進む |
| `python`が見つからない | Python 3.11以上を導入し、`python --version`を確認する |
| `FileNotFoundError` | このREADMEがある`s5`ディレクトリで実行しているか確認する |
| manifest hash mismatch | fixtureと`fixtures/manifest.json`を配布時の同じ版へ戻す |
| expected resultsと不一致 | fixture、`analyze.py`、`expected-results.json`を同じ版にそろえる |

## コスト

この演習の手順は新しいAWS/Kubernetesリソースを作らないため、読み取り手順そのものによる新規リソース費用は発生しません。ただし、参照する既存EKSクラスタ、Node、CloudWatch Logs、Container Insights、メトリクス、alarm、dashboardなどには、演習以前から料金が発生している場合があります。この演習はそれらの既存料金を停止または変更しません。fixture routeはローカル標準ライブラリだけを使い、追加のクラウド費用はありません。

## クリーンアップ

この演習はAWSリソースやKubernetesリソースを作成・変更しないため、クラウド側のクリーンアップはありません。既存cluster、workload、CloudWatch設定をこの演習のcleanupとして削除しないでください。任意でローカル出力を保存した場合だけ、その出力ファイルを通常のファイル操作で削除できます。`fixtures/`、`expected-results.json`、`analyze.py`、`tests/`は教材なので削除しません。

## ファイル構成

- `fixtures/`: 固定済みの合成Pod、Node、describe、logs、events
- `expected-results.json`: 決定的な期待結果
- `analyze.py`: fixtureの整合性と診断結果を検証する標準ライブラリのみのプログラム
- `tests/`: 正常系、fail-closed動作、hybrid labの安全境界を検証する単体テスト
