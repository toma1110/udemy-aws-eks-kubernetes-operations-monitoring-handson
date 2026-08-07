# Section 10: 演習resourceを完全削除して残存を確認する（s10-l1-cleanup）

この演習では、Section 3で作成した専用EKS on AWS Fargate環境を、依存関係の逆順で削除します。対象はcanonical固定名の学習用resourceだけです。共有resource、別名resource、ownershipを証明できないresourceは削除しません。

> 手順1はlocal/static validationだけで、AWSへ接続しません。手順2以降のAWS／Kubernetes commandは、受講者が自分の専用非本番環境で対象を確認して実行します。

## 到達点

- AWS identity、Region、cluster ARN、Kubernetes context、ownership tagを照合し、対象が1件に固定できないときに停止できる。
- namespace内resource → logging ConfigMap → IRSA依存 → Fargate Profile → cluster/VPC → CloudWatch Logsの順でcleanupできる。
- EKS、Fargate、IAM、CloudWatch Logs、CloudFormation、VPC/NATをservice別のread-only commandで確認し、残存0またはowner付き保持を記録できる。
- 部分作成や途中失敗を「削除済み」と読み替えず、残存した段階から安全に再開できる。

## 料金と時間

EKS cluster、Fargate vCPU／memory、NAT Gateway、CloudWatch Logsの取り込み・保存には、cleanup完了まで料金が発生し得ます。削除処理には30分以上かかる場合があります。開始前に最新の[EKS pricing](https://aws.amazon.com/eks/pricing/)、[Fargate pricing](https://aws.amazon.com/fargate/pricing/)、[CloudWatch pricing](https://aws.amazon.com/cloudwatch/pricing/)を確認し、少なくとも60分の作業時間を確保してください。

途中で画面を閉じても、resourceが自動的に消えるとは限りません。削除commandの失敗、timeout、`DELETE_FAILED`、`AccessDenied`が1件でもあれば、残りの削除を推測で続けず、`cleanup-record.md`へ最後の成功点を記録します。

## 1. 配布ファイルを静的検査する

AWS CloudShellのBashで、このREADMEがあるdirectoryへ移動します。次の検査はAWSやKubernetesへ接続しません。

```bash
export PYTHONDONTWRITEBYTECODE=1
python validate_package.py --check
python -m unittest discover -s tests -v
bash -n capture-target-record.sh cleanup.sh verify-residuals.sh
python -c 'from pathlib import Path; paths=[Path(x) for x in ("capture_target_record.py","execute_preflight.py","runtime_contract.py","validate_package.py","tests/test_package.py","tests/test_runtime_contract.py")]; [compile(p.read_text(encoding="utf-8"),str(p),"exec") for p in paths]; print("PASS: Python sources compile in memory")'
```

Windows PowerShellで同じlocal検査を行う場合は、先に`$env:PYTHONDONTWRITEBYTECODE="1"`を設定し、Bash構文検査以外の同じ`python` commandを実行します。終了後は`Remove-Item Env:PYTHONDONTWRITEBYTECODE`で一時設定を解除できます。`py_compile`はpackage内へ`__pycache__`を生成するため使用しません。

期待結果:

```text
PASS: Section 10 cleanup package satisfies the local safety contract
```

## 2. exact targetを固定する

Section 3と同じAWS accountのCloudShellを使います。実際の12桁account IDは画面で確認し、公開repositoryや共有先には記録しません。

```bash
export AWS_REGION="ap-northeast-1"
export AWS_DEFAULT_REGION="$AWS_REGION"
export CLUSTER_NAME="eks-fargate-ops-lab"
export NAMESPACE="eks-fargate-ops"
export EXPECTED_AWS_ACCOUNT_ID="<自分の12桁account ID>"
export CONFIRM_CLEANUP_TARGET="DELETE eks-fargate-ops-lab IN ap-northeast-1"
export TARGET_RECORD_PATH="$HOME/c010-s3-cleanup-target.private.json"

aws --version
eksctl version
kubectl version --client --output=yaml
aws sts get-caller-identity
bash capture-target-record.sh "$TARGET_RECORD_PATH"
```

`EXPECTED_AWS_ACCOUNT_ID`は削除対象の照合だけに使います。`capture-target-record.sh`はexact ownership tag付きcluster CloudFormation stack ARNと完全なlogical-ID／type／physical-ID populationをprivate fileへ結合します。clusterがreadableならOIDC、Pod Execution Role、IRSA stackも結合し、cluster-create失敗時は存在するOIDC／role／VPC／NATとoptional IRSA stackだけをexactに記録します。名前だけからidentityを推測しません。permissionは600にし、公開repositoryや共有先には記録しません。cleanupと残存確認が終わったらCloudShellから削除します。`cleanup.sh`は次をすべて満たさなければ、最初の削除commandより前に停止します。

clusterがreadableなpartial stateでは、IRSA stackやworkload Profileの有無に関係なくcluster identityからOIDC issuerを取得し、同じaccountのexact OIDC provider ARNをread-onlyで照合します。OIDC providerがcluster CloudFormation stack memberであるとは仮定しません。

partial customer-managed policyは、capture時にimmutable `PolicyId`と`Course=c010`、`Section=s3`、`ManagedBy=learner`、`Purpose=training` tagsを取得できた場合だけ削除候補になります。同じpolicy名と同じJSON文書だけでは削除しません。tagまたはPolicyIdの証跡がなければ、ownerへ引き渡します。

- STS account IDが入力した12桁IDとexact一致する。
- Regionが`ap-northeast-1`、cluster名が`eks-fargate-ops-lab`である。
- EKS cluster ARNが入力account、Region、cluster名から組み立てたexact ARNと一致する。
- cluster tagが`Course=c010`、`Section=s3`、`ManagedBy=learner`、`Purpose=training`と一致する。
- Kubernetes current contextが同じexact cluster ARNである。
- namespaceが存在する場合、label `course=c010`と`section=s3`が一致する。
- Fargate Profileは`ops-workloads`と`system-coredns`以外に存在せず、それぞれのselectorとownership tagがSection 3の構成と一致する。
- Profile一覧APIが成功し、一覧にある各Profileのdescribeも成功する。describe errorを不存在と扱わない。
- private recordの2つのtag付きCloudFormation stackと全resource一覧が現在値とexact一致する。
- IRSA／Pod Execution Roleのtrust、attached／inline policy一覧と文書、IRSA policy attachment、OIDC参照元がSection 3のexact構成と一致する。
- IRSA policyとPod Execution Role logging policyはSection 3の配布JSONと同じ`Sid`、`Version`、action、resource（IRSAはwildcard-account ARN）である。

clusterが既にない部分作成状態でも、事前取得したprivate recordと、現在取得できる2つのexact CloudFormation stack ARN、4つのownership tag、全stack resource、IAM／OIDC構成が一致する場合だけ進みます。private recordがない、tagが違う、stackまたはresource一覧が読めない、record取得後にmemberが増減した場合は削除しません。

## 3. 削除予定を表示する

最初は`--plan`だけを実行します。これはread-only確認だけを行い、削除commandを実行しません。

```bash
bash cleanup.sh --plan
```

期待結果:

```text
PASS: complete read-only preflight for exact cleanup target
PLAN: namespace eks-fargate-ops
PLAN: logging ConfigMap aws-observability/aws-logging
PLAN: delete exact iamserviceaccount through eksctl
PLAN: Fargate profiles ops-workloads, system-coredns
PLAN: eksctl cluster stack, VPC, and NAT resources
PLAN: CloudWatch Logs group /aws/eks/eks-fargate-ops-lab/containers
```

IRSA行はvalidated decisionにより次のどちらか1行です。readable clusterでcaptured exact roleが存在するときは`PLAN: delete exact iamserviceaccount through eksctl`、failed empty stackでroleが存在しないときは`PLAN: delete exact captured iamserviceaccount CloudFormation stack`になります。両方を同時に表示せず、generic IRSA planへ戻しません。

表示された値がSection 3で自分が作成した対象と違う、Profileが3件以上ある、namespace labelが違う、logging ConfigMapが別log groupを指す、IAM policyが別roleに接続されている場合は実行しません。共有resourceのownerと削除方法を管理者へ確認します。

## 4. 依存関係の逆順で削除する

`--execute`は実際にAWS／Kubernetes resourceを削除します。planの確認後だけ実行します。

```bash
export CLEANUP_DEADLINE_EPOCH="$(($(date +%s) + 3600))"
bash cleanup.sh --execute | tee cleanup-session.log
```

scriptは次の順で進み、各段階が成功した場合だけ次へ進みます。

1. 対象namespace内のworkload、Job、ServiceAccount、Role／RoleBindingをnamespaceごと削除し、`NotFound`を確認する。
2. `aws-observability/aws-logging`が専用log groupを指すexact ConfigMapである場合だけ削除する。`aws-observability` namespace自体は共有の可能性があるため削除しない。
3. `irsa-reader`のiamserviceaccountを`eksctl`で削除し、専用IAM role stackを削除する。専用customer-managed policyが他のrole/user/groupに接続されていない場合だけpolicyを削除する。
4. cluster固有OIDC providerを参照するroleが残っていないことを確認してから、そのexact providerだけを削除する。
5. Pod Execution Roleの専用inline logging policyだけを削除する。role本体はeksctl cluster stackの管理対象なので直接削除しない。
6. `ops-workloads`を削除して完了を待ち、次に`system-coredns`を削除して完了を待つ。Fargate Profileは同時に複数削除しない。
7. `eksctl delete cluster --wait`でcluster stackと、Section 3が作成したVPC／NAT依存を削除する。
8. 専用CloudWatch log groupを削除する。
9. `verify-residuals.sh`を実行する。

60分budgetの最後180秒はrecord-bound残存確認専用に予約します。すべての削除request、wait、polling intervalはmutation deadlineの残り時間を使います。deadline到達またはtimeoutでは共通の`incomplete` handlerが後続mutationを止め、予約時間内でread-only残存確認を必ず試行します。

`cleanup-session.log`にはaccount IDやARNが含まれる可能性があります。学習終了後に内容を確認し、`cleanup-record.md`へsecretやaccount情報を含まない結果だけ転記してから、CloudShell上のlogを削除してください。logをGitへ追加しません。

## 5. service別に残存を確認する

cleanup scriptの最後にも呼ばれますが、再開時は単独で実行できます。これはread-onlyです。

```bash
export TARGET_RECORD_PATH="$HOME/c010-s3-cleanup-target.private.json"
bash verify-residuals.sh
```

期待結果:

```text
PASS: EKS cluster absent
PASS: Fargate profiles absent with cluster
PASS: dedicated IAM role absent
PASS: dedicated IAM policy absent
PASS: cluster OIDC provider absent
PASS: CloudWatch log group absent
PASS: active eksctl CloudFormation stacks absent
PASS: tagged VPC and NAT Gateway resources absent
PASS: no billable training resource residual was detected
```

`verify-residuals.sh`はprivate recordのexact stack ID、VPC ID、NAT Gateway IDを個別に問い合わせ、その後に広いtag/name discoveryも追加で行います。API errorを「0件」にしません。`AccessDenied`、credential／network error、queryの空でない結果、`DELETE_FAILED`、NAT Gatewayの`available`／`deleting`があればfailです。`deleting`は完了ではないため、待って再確認します。

## 部分作成・途中失敗から再開する

fresh shellではprivate recordを作り直しません。次のexact commandで環境を再設定し、`--plan`の完全read-only restart preflightを通してから`--execute`します。

```bash
export AWS_REGION="ap-northeast-1"
export AWS_DEFAULT_REGION="$AWS_REGION"
export CLUSTER_NAME="eks-fargate-ops-lab"
export NAMESPACE="eks-fargate-ops"
export TARGET_RECORD_PATH="$HOME/c010-s3-cleanup-target.private.json"
export EXPECTED_AWS_ACCOUNT_ID="$(python -c 'import json,os; print(json.load(open(os.environ["TARGET_RECORD_PATH"],encoding="utf-8"))["account_id"])')"
export CONFIRM_CLEANUP_TARGET="DELETE eks-fargate-ops-lab IN ap-northeast-1"
bash cleanup.sh --plan
export CLEANUP_DEADLINE_EPOCH="$(($(date +%s) + 3600))"
bash cleanup.sh --execute
```

preflightはcomplete／partialそれぞれについてcluster-readableとcluster-absentを別々に扱います。各列で許可されたexact creation／restart populationだけを受け入れ、途中段階のskip、後段削除後の前段残存、unexpected member、unreadable stateはmutation前に停止します。cleanupから呼ぶ残存確認にも同じdeadlineの残り時間が渡り、verifier内のすべてのAWS callがその時間で打ち切られます。

partial IRSA stackで期待するroleの有無はstack自体の存在ではなく、capture済みのexact resource populationに`AWS::IAM::Role`が含まれるかで決めます。作成失敗stackのresource populationが空ならraw roleは不在でなければならず、exact stackだけを削除計画に含めます。

complete recordになるのはIRSA stackにlogical ID `Role1`、type `AWS::IAM::Role`、physical ID `eks-fargate-ops-irsa-reader`がexact一致し、そのresource stateが`CREATE_COMPLETE`または`UPDATE_COMPLETE`の場合だけです。空population、`CREATE_FAILED`、`CREATE_IN_PROGRESS`はpartial recordとして扱います。

`--plan`と`--execute`は、validated private recordと同じrestart snapshotから生成した1つのdeterministic IRSA cleanup decisionを共有します。roleが存在するreadable clusterではexact iamserviceaccount route、failed empty stackではexact captured CloudFormation stack routeだけを表示・実行し、route決定前のgeneric IRSA planは表示しません。

- cluster作成が途中で失敗した: exact ownership tagを持つEKS clusterがreadableな時点でprivate target recordをcaptureします。clusterがなくなった後も、recordと現在の2つのstackおよび全resource一覧がexact一致する場合だけplanへ進みます。
- namespaceだけ削除済み: planで`NotFound`を確認し、残るlogging／IAM／Fargateへ進みます。
- IRSA作成が途中で失敗した: clusterがreadableならiamserviceaccount削除を使います。clusterがないIAM-only状態では、事前captureしたprivate recordとexact trust／attachmentが一致する場合だけrecord内のrole/policyへ進み、recordがなければ停止します。
- Fargate Profileが`DELETING`: 次のProfileを削除せず、最初の削除完了まで待ちます。
- cluster stackが`DELETE_FAILED`: CloudFormation Eventsで残存resourceをread-only確認し、対象とownerを管理者へ引き継ぎます。VPCやNAT Gatewayを手動で広く削除しません。
- log groupだけ残った: ownership-proven private recordが同じaccount、Region、cluster、exact log groupを結合する場合だけ削除します。recordがなければ名前だけで削除しません。

## Troubleshooting

- `STOP: exact target verification failed`: account、Region、cluster ARN、tag、contextのどれかが違います。値を変更して通過させず、Section 3の作成記録と管理者確認へ戻ります。
- `unexpected Fargate profile`: Course外のProfileまたは共有利用の可能性があります。削除しません。
- `IAM policy still attached`: 接続先をread-onlyで確認し、Course外ownerが1件でもあればpolicyを削除しません。
- `OIDC provider still referenced`: trust policyを使うroleを先にownerへ確認します。参照中のproviderを削除しません。
- `ResourceNotFoundException`／`NoSuchEntity`: 対象APIが成功し、exact not-foundである場合だけ削除済みとして扱います。
- `AccessDenied`: 権限をその場で追加せず、拒否actionとexact対象を管理者へ渡します。
- 残存確認が0件にならない: `cleanup-record.md`を`incomplete`にし、service、exact resource名、状態、次のownerを記録します。

## 完了条件

service別検査がすべてpassし、`cleanup-record.md`にUTC時刻、結果、保持対象とowner（なければ`なし`）を記録して初めてcleanup完了です。scriptの終了、clusterの非表示、`kubectl`接続不能だけでは完了にしません。

## 公式資料（2026-08-07確認）

- [EKS clusterを削除する](https://docs.aws.amazon.com/eks/latest/userguide/delete-cluster.html)
- [eksctlでclusterを削除する（`--wait`）](https://docs.aws.amazon.com/eks/latest/eksctl/creating-and-managing-clusters.html)
- [Fargate Profileを削除する](https://docs.aws.amazon.com/eks/latest/APIReference/API_DeleteFargateProfile.html)
- [IAM OIDC providerを削除する](https://docs.aws.amazon.com/IAM/latest/UserGuide/iam_example_iam_DeleteOpenIdConnectProvider_section.html)
