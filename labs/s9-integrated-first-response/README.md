# 5つの症状を一つの初動手順で解く

この演習では、5つの独立した障害記録を同じ順序で調べます。エラー名から原因を決めず、Pod状態、describe／Events、container logs、CloudWatch Logs、配置または権限設定の順に証拠をつなぎます。最後に、変更差分が開始前の正常値へ戻ったかを確認し、担当者へ渡せる初動記録を完成させます。

## 対応する講義

| 講義 | この演習で行うこと |
| --- | --- |
| `s9-l0-preview` | 5つの症状と共通の調査順序を確認する |
| `s9-l1` | `Pending`と`CrashLoopBackOff`を配置とapplication設定から区別する |
| `s9-l2` | AWS APIの`AccessDenied`とKubernetes APIの`Forbidden`を主体とアクセス先で区別する |
| `s9-l3` | CloudWatch Logsのapplication errorをcontainer logとrequest IDで対応付ける |
| `s9-l4` | 自分で戻す差分と、管理者へ引き継ぐ変更を分ける |
| `s9-l5` | 5シナリオの復旧値と正常化結果をまとめて確認する |

## できるようになること

- どの症状でも、変更前のread-onlyな観察から始められる。
- Fargate Profile、application設定、IRSA、RBAC、CloudWatch Logsの証拠を混同せずに使える。
- 専用resourceの既知差分だけを開始前の値へ戻し、`Running`だけでなくReady、ログ、権限結果まで確認できる。
- IAM、Fargate Profile、cluster／VPC、共有resourceの変更が必要なら、推測で変更せず根拠付きで停止・引き継ぎできる。

## ルートを選ぶ

まず、AWSへ接続しない教材用の固定データで練習します。5つの固定データにはaccount ID、credential、Secret値を含めていません。

live確認は、Section 3で作成し正常値を記録済みの専用非本番環境だけを対象とする補助手順です。本教材のlive手順はread-only確認に限定し、障害注入や復旧操作を含みません。共有環境や本番環境では実行しないでください。

## 前提条件

固定データルート:

- Python 3.11以上
- このrepositoryのcheckout
- AWS credentialは不要

liveのread-only補助確認:

- Section 3の`eks-fargate-ops-lab`が正常化済みであること
- AWS Management Consoleの東京Regionから起動したAWS CloudShell Bash
- `AWS_REGION=ap-northeast-1`、namespace `eks-fargate-ops`
- 対象cluster、context、namespace、終了時刻、料金要因を確認済みであること

## 料金と時間上限

固定データルートはAWSを使わないためAWS料金は発生しません。

live環境では、EKS cluster、Fargate vCPU／memory、NAT Gateway、CloudWatch Logsの取り込み・保存、Logs Insightsでscanしたデータ量などが料金要因です。料金はRegion、利用時間、通信量、ログ量、割引などで変わるため、実行直前に[AWS公式のEKS料金](https://aws.amazon.com/eks/pricing/)、[Fargate料金](https://aws.amazon.com/fargate/pricing/)、[CloudWatch料金](https://aws.amazon.com/cloudwatch/pricing/)を確認してください。Section 3で決めた90分の環境上限を延長しません。上限到達、対象不明、権限不足、想定外の課金要因があれば停止し、[s10-l1-cleanup](../s10-cleanup/README.md)へ進みます。

## 1. 共通の初動順序を固定する

各シナリオで次の順序を守ります。途中の情報で原因を断定せず、次の情報源が必要かを判断します。

1. 症状と対象時刻を固定する。
2. Pod状態と対象Podを確認する。
3. describeとEventsでscheduling、container state、直近の変化を確認する。
4. current／previous container logsを使い分ける。
5. 複数Podまたは過去時間帯が必要な場合だけCloudWatch Logsへ進む。
6. 証拠が示す経路だけ、Fargate Profile、IRSA、RBACを確認する。
7. 専用resourceの既知差分だけを開始前の値へ戻す。または、変更せず停止して引き継ぐ。
8. Ready、期待ログ、権限結果を確認してから次のシナリオへ進む。

## 2. 固定データとtestを準備する

repository rootから次を実行します。

```bash
cd labs/s9-integrated-first-response
python -m unittest discover -s tests -p "test_*.py" -v
```

期待結果は14件のtestがすべて`ok`となり、最後に`OK`と表示されることです。この段階ではanalyzerを起動しません。`fixtures/scenarios.json`の5件を読み、Pod状態、ログ、権限、開始前の正常値、復旧後の観察値を確認します。

想定と異なる場合は、最初にPython version、現在directory、固定データの変更有無を確認します。テストを通すために期待結果を書き換えず、`git diff -- fixtures/scenarios.json expected-results.json`で差分を確認してください。

## 3. 自分の診断と対応を入力する

`templates/learner-decisions.json`を作業用ファイルへ複製します。各scenarioの証拠を読んでから、次の4項目を入力してください。最初の回答を作る前に`expected-results.json`を答えとして使わないでください。

```bash
cp templates/learner-decisions.json learner-decisions.json
```

- `diagnosis`: 原因候補を5つの診断codeから1つ選ぶ。
- `correction`: 専用resourceへ加えられた1差分だけを戻す操作codeを選ぶ。
- `normalization_fields`: `baseline`と`post_restoration`を比較し、Ready、期待ログ、権限結果を含む必要fieldを順に記入する。
- `escalation`: 共有基盤や権限変更が必要な場合の停止・引き継ぎcodeを選ぶ。

選択肢は次のとおりです。scenarioとの対応は証拠から判断します。

| 項目 | 選択肢 |
| --- | --- |
| diagnosis | `fargate-profile-selector-mismatch` / `application-config-mismatch` / `irsa-service-account-annotation-mismatch` / `rbac-rolebinding-subject-mismatch` / `application-endpoint-config-mismatch` |
| correction | `restore-compute-label` / `restore-app-mode` / `restore-irsa-annotation` / `restore-rolebinding-subject` / `restore-application-endpoint` |
| escalation | `escalate-profile-or-shared-change` / `escalate-unknown-or-shared-config` / `escalate-iam-or-shared-identity-change` / `escalate-cluster-scope-or-auth-change` / `escalate-shared-endpoint-or-log-path-change` |

5件すべてを入力し、ファイルを保存してから、初めてanalyzerへ渡します。`--answers`を省略した起動は受理されません。

```bash
python triage.py fixtures/scenarios.json --answers learner-decisions.json --format markdown
```

5件すべてで診断、1差分の復旧、正常化field、引き継ぎ判断が一致すると、`learner_answers_passed: true`を表示して終了code `0`になります。不一致または欠落があるscenarioは`review-required`となり、終了code `1`になります。自分の回答を見直してから`expected-results.json`と比較してください。`restored_to_baseline: true`のような自己申告fieldは回答として受理されません。

## 4. 5つの証拠を読む

`templates/first-response-record.md`を複製し、各シナリオについて次を記録します。

- 観察した症状とUTC時刻
- 最初の仮説と、反証できた候補
- 原因候補を支える証拠
- 変更対象と開始前の正常値
- 復旧後のReady、期待ログ、権限結果
- 自分で戻すか、管理者へ引き継ぐか

### Scenario 1: Pending

Pod labelの`compute`とFargate Profile selectorを比較します。教材用の固定データではnamespaceは一致し、labelだけが開始前の`ops-lab`と異なります。Pod内applicationはまだ開始していないため、IRSAやcontainer logを原因根拠にしません。

正常化はlabelを`compute=ops-lab`へ戻し、PodがFargateへ配置され、Ready `1/1`になることです。Profile自体の変更が必要なら、Profileは更新できず置換になるため、この演習では変更せず管理者へ引き継ぎます。

### Scenario 2: CrashLoopBackOff

containerは開始済みなので、last stateとprevious logを優先します。教材用の固定データではexit code `42`と`APP_MODE=broken`が対応し、image pull、scheduling、probeの候補は反証できます。

正常化は専用ConfigMapの学習用差分を`APP_MODE=baseline`へ戻し、Ready `1/1`、restart増加停止、`config=baseline`の期待ログを確認することです。restartのためだけにPod削除を繰り返しません。

### Scenario 3: AWS API AccessDenied

アクセス先はAWS API、主体は`irsa-reader`を使うPod内applicationです。教材用の固定データではPod Execution Roleではなく、ServiceAccount annotationだけが開始前のroleと不一致です。IAM trustと最小policyが開始前どおりである証拠も合わせて確認します。

正常化は専用ServiceAccountのannotationを開始前に記録したroleへ戻し、新しく起動した検証Podで許可された`eks:DescribeCluster` readが`ACTIVE`になることです。IAM policy、trust、Pod Execution Roleを広げる必要がある場合は変更せず、IAM担当者へ引き継ぎます。

### Scenario 4: Kubernetes API Forbidden

アクセス先はKubernetes API、主体は`rbac-reader`です。教材用の固定データでは認証済みですが、RoleBindingのsubjectだけが別名です。AWS IAMの`AccessDenied`とは別経路です。

正常化は専用RoleBindingのsubjectを`rbac-reader`へ戻し、`get configmaps=yes`と`delete configmaps=no`を確認することです。`cluster-admin`を付けて試しません。

### Scenario 5: CloudWatch application error

直近の単一Pod logと、CloudWatch Logsの同じUTC時間帯を比較します。教材用の固定データではnamespace、Pod、container、request ID、error codeが一致します。CloudWatch Logsで見つかったerrorを、別Podのcontainer errorの証拠に流用しません。

`queries/application-error.logs-insights`は対象log groupを選び、時間範囲を直近15分へ絞ってから使用します。正常化はapplication設定を開始前の値へ戻し、同じrequestが`result=ok`となり、新しい同種errorが増えないことです。0件の場合は異常なしとせず、Pod出力、logging ConfigMap、Pod Execution Role、Region、log groupの順へ戻ります。

## 5. 修正か引き継ぎかを決める

自分で戻せるのは、対象、影響、開始前に記録した値、元に戻す手順が分かる専用resourceの学習用差分だけです。次のどれかに該当したら変更せず停止します。

- AWS identity、Region、cluster、context、namespace、対象resourceを一意に確認できない。
- 開始前の正常値、変更差分、元に戻す手順のどれかが不明。
- IAM policy／trust、Fargate Profile、cluster、VPC、共有resourceの変更が必要。
- 複数の設定を同時に変えないと仮説を試せない。
- credential、Secret値、account IDの表示や共有を求められた。
- 90分の環境上限へ到達した、費用が不明、または中断する。

引き継ぎには、症状、UTC時間帯、主体、アクセス先、観察した証拠、反証した候補、必要な変更候補、変更後に期待する状態、停止理由を含めます。credential、Secret値、account IDは含めません。

## 6. live環境をread-onlyで照合する（任意）

以下はSection 3の専用非本番環境が正常化済みの場合だけ使うread-only確認です。教材用の固定データを、自分のlive環境の実行結果として扱わないでください。

```bash
export AWS_REGION="ap-northeast-1"
export CLUSTER_NAME="eks-fargate-ops-lab"
export NAMESPACE="eks-fargate-ops"
export FARGATE_PROFILE="ops-workloads"

aws sts get-caller-identity --query Arn --output text
aws eks describe-cluster --region "$AWS_REGION" --name "$CLUSTER_NAME" --query 'cluster.status' --output text
kubectl config current-context
kubectl get pods -n "$NAMESPACE" -o wide
kubectl get events -n "$NAMESPACE" --sort-by=.metadata.creationTimestamp
aws eks describe-fargate-profile --region "$AWS_REGION" --cluster-name "$CLUSTER_NAME" --fargate-profile-name "$FARGATE_PROFILE" --query 'fargateProfile.{status:status,selectors:selectors}' --output json
kubectl auth can-i get configmaps --as=system:serviceaccount:"$NAMESPACE":rbac-reader -n "$NAMESPACE"
kubectl auth can-i delete configmaps --as=system:serviceaccount:"$NAMESPACE":rbac-reader -n "$NAMESPACE"
```

出力は画面で照合し、account IDを記録へ貼り付けません。permission、credential、network errorをresource不存在と読み替えません。この補助確認には障害注入、`apply`、`patch`、`delete`、IAM変更、Profile置換を含めません。

## 7. 全シナリオの正常化を確認する

固定データでは、5件すべてに開始前の`baseline`と復旧後に観察した`post_restoration`があります。analyzerはscenarioごとに次を比較し、一致した場合だけ復旧済みと導出します。

- Pending: label、Pod phase、Ready
- CrashLoopBackOff: application設定、Ready、restart増加停止、期待ログ
- AccessDenied: ServiceAccount annotation、検証主体、許可されたAWS read、AccessDenied解消
- Forbidden: RoleBinding subject、許可する操作、拒否を維持する操作
- CloudWatch application error: endpoint、Ready、request成功、新しい同種error件数

必要fieldが1つでも欠ける、または開始前と異なる場合、`restoration_complete`は`false`になります。教材用の固定データや回答へ復旧済みの真偽値を書くだけでは合格しません。

live環境では、各シナリオの直後にそのシナリオだけを開始前へ戻し、Ready、期待ログ、権限結果を確認してから次へ進みます。Section 3の正常値へ戻せない場合は次へ進みません。

このSectionではCourse共通resourceを完全削除しません。中断時、90分到達時、またはCourse終了時は、`s10-l1-cleanup`「演習resourceを完全削除して残存を確認する」へ直行し、EKS、Fargate、IAM、CloudWatch Logs、VPCの残存をservice別に確認します。共有resourceは削除しません。

## 公式資料

- [Fargate Profileのselectorと置換](https://docs.aws.amazon.com/eks/latest/userguide/fargate-profile.html)
- [Pod Execution RoleとPod内applicationの権限の違い](https://docs.aws.amazon.com/eks/latest/userguide/pod-execution-role.html)
- [EKS on Fargateの組み込みlog router](https://docs.aws.amazon.com/eks/latest/userguide/fargate-logging.html)
- [IAM roles for service accounts（IRSA）](https://docs.aws.amazon.com/eks/latest/userguide/iam-roles-for-service-accounts.html)
- [CloudWatch Logs Insights query syntax](https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/CWL_QuerySyntax.html)
