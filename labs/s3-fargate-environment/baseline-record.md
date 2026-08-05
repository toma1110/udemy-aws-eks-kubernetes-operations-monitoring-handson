# Section 3 baseline observation record

Secret、credential、account ID、role ARNは記録しません。確認できない値は空欄にせず`未確認`と書きます。

- UTC time:
- AWS CLI version:
- eksctl version:
- kubectl client version:
- Python version:
- Region:
- cluster:
- Kubernetes context:
- namespace:
- Fargate Profile status:
- Profile namespace / label selector:
- Fargate subnet count / IDs（account情報を含む画面共有はしない）:
- Subnet route-table check（direct Internet Gateway routeなし）:
- CoreDNS desired / Ready / available:
- Pod name:
- Pod phase / Ready / restart count:
- current log sample（Secret値を除く）:
- CloudWatch log group / stream / UTC window:
- IRSA ServiceAccount:
- IRSA check image version:
- `eks:DescribeCluster` result (`ACTIVE` / error):
- RBAC `get configmaps` result:
- RBAC `delete configmaps` result:
- 90-minute deadline UTC:
- Next action: proceed / recover baseline / go directly to s10-l1-cleanup
