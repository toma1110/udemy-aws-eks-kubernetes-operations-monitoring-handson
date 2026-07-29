# 権限まわりの初動観察メモ

## 発生した事象

- 実行したcommand:
- errorまたは欠落したデータ:
- 発生時刻とRegion:

## Kubernetes側

- 対象namespace / ServiceAccount:
- RoleBinding / ClusterRoleBinding:
- `Forbidden` / `Unauthorized`の有無:

## AWS側

- `AccessDenied`の有無:
- denied action:
- IRSA annotationの有無:
- Pod Identity associationの有無:
- EKS access entryを確認できたか:

## 次の確認

- 明示的に確認できた事実:
- まだ確認できていない層:
- 管理者へ共有する内容:

> account ID、principal ARN、credential、tokenはこのメモへ貼り付けません。

