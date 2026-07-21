# 02. `describe`、`logs`、eventsで深掘りする

Section 2の演習は、AWSアカウントやKubernetesクラスターを使わない固定データ版へ移動しました。

[固定データで行うKubernetes初動診断](s2-kubernetes-initial-triage/README.md)の手順4から6で、同じnamespaceとPodの`describe`、現在・前回logs、eventsを照合し、Pending、CrashLoopBackOff、OOMKilledの初動仮説を作ります。

結果は原因確定ではありません。複数の根拠を組み合わせ、次に確認する項目まで記録します。
