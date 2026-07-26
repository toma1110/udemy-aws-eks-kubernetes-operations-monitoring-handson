# Expected results

これは期待値であり、保存済みのAWS実行結果ではありません。

| Step | Expected observation | Variable fields |
| --- | --- | --- |
| common status | CloudFormation stack is complete, EKS cluster is active, at least one Node is Ready | ARN, Node name/IP, timestamps |
| apply | exact Namespace exists; exactly one matching Pod is Running/Ready and has the exact ReplicaSet→Deployment controller UID chain; Deployment desired/ready/available replicas are 1; ClusterIP Service has exactly one ready endpoint bound only to that Pod | Pod suffix/IP, UIDs, ClusterIP |
| get | Nodes, namespaces, all Pods, and exact Section workload are listable | system Pod count/order |
| describe | baseline Pod is Running/Ready and shows scheduling/container lifecycle | event messages/count/times |
| logs | `baseline-started` and at least one `baseline-heartbeat` appear | repetition count |
| events | normal scheduling/image/container events may appear | reason order, wording, count |
| Section cleanup | Namespace JSON lookup exits 0 with empty output | deletion duration |
| common cleanup | s2 wrapper proves the Namespace absent, then common cleanup completes its residual checks | deletion duration |

`Pending`、`CrashLoopBackOff`、`OOMKilled`は説明対象ですが、この安全なbaselineの期待状態ではありません。実際に観測していない異常状態を実結果として記録しません。
