# 05. PendingとCrashLoopBackOffの初動対応

実習本体は[Pending / CrashLoopBackOffの初動切り分け](s5-pod-resource-first-response/README.md)です。

- EKS環境で確認する: [共通EKS基盤](common-eks/README.md)で短時間だけ使うEKSクラスタと1台のNodeを作り、Section専用namespaceに3つのPodを配置します。AWS費用と作成・削除操作を伴います。
- AWSを使わずに確認順序を練習する: Python 3.11以上で、用意されたサンプル結果を分析します。AWSアカウントやKubernetesクラスタは不要で、追加のクラウド費用はありません。

EKS環境で確認する場合は、使用するAWSアカウント、`ap-northeast-1`、2つのAZ、自分の接続元だけを許可する`/32` CIDR、削除期限を確認します。基礎概算は約USD 0.97/6時間ですが、データ転送、CloudWatch、税、為替、価格変更などは含みません。実行直前に公式料金を確認してください。

## 実行順序

```bash
cd labs/s5-pod-resource-first-response
```

1. 実習本体READMEのpreflightを実行する。
2. 共通EKS基盤を作成し、cluster `ACTIVE`、Node `Ready`を確認する。
3. Section scenarioをapplyする。
4. `get`で状態を見つけ、`describe`とイベントで配置・終了理由を確認し、`logs --previous`で再起動前のログを読む。
5. Section namespaceを先に削除する。
6. 共通EKS基盤を削除し、stack、cluster、EC2、EBS、ENI、CloudWatch残存がないことを確認する。

途中で失敗しても、作成済みの外部cleanup guardを自己判断で消さないでください。Section cleanupの後、CloudShellのBashで`"$COMMON_EKS_DIR/scripts/delete.sh"`を実行します。残存確認が失敗した場合、guardは保持されます。

## 調査時の確認コマンド

```bash
kubectl get pods -n udemy4-c010-s5-20260724 -o wide
kubectl get events -n udemy4-c010-s5-20260724 --sort-by=.lastTimestamp
kubectl describe pod udemy4-c010-s5-20260724-pending-capacity -n udemy4-c010-s5-20260724
kubectl describe pod udemy4-c010-s5-20260724-crashloop-app -n udemy4-c010-s5-20260724
kubectl logs udemy4-c010-s5-20260724-crashloop-app -n udemy4-c010-s5-20260724 --previous --tail=100
kubectl describe pod udemy4-c010-s5-20260724-crashloop-memory -n udemy4-c010-s5-20260724
kubectl logs udemy4-c010-s5-20260724-crashloop-memory -n udemy4-c010-s5-20260724 --previous --tail=100
```

## 記録欄

```text
症状:
対象Pod:
namespace:
Node:
イベント:
ログ:
初動仮説:
次に確認する情報:
```

観察できた事実だけを記録します。別Podのイベントやログを代用せず、状態名だけで原因を確定しません。具体的な期待結果、AWSを使わない練習方法、費用、cleanup、残存確認は実習本体READMEを参照してください。
