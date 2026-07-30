# EKS初動対応Runbook

## 基本情報

- 記録時刻: `2026-07-31T00:00:00Z`
- 症状: `sample-api Podの再起動回数が増加`
- 開始時刻: `不明`
- 影響範囲: `sample namespaceのsample-api`
- 変更承認者: `環境の所有者`

## 観察した事実

- Pod: `sample-apiはRunning、RESTARTSは3、sample-nodeへ配置`
- Node: `sample-nodeはReady、pressureなし`
- Event: `sample-apiにBackOff、fixture時刻内`
- Log / Metric: `fixtureの直近logに起動失敗、CPU異常は未確認`
- 権限: `Forbidden、Unauthorized、AccessDeniedは観察されていない`

## まだ分からないこと

- `再起動直前の設定変更と依存先の状態`

## 仮説

- `起動時の依存先接続失敗が再起動に関係する可能性がある`

## 次の安全な確認

1. `previous container logとDeploymentの変更履歴を読み取る`
2. `再起動や設定変更は環境の所有者の承認後に行う`

## エスカレーション条件

- `影響が別namespaceへ広がる、または15分以内に安全な読み取りで原因候補を絞れない`

## コストとcleanup

- 課金中の可能性があるresource: `sample-cluster、ap-northeast-1`
- 所有権を確認した方法: `fixtureのstack名と所有権tag`
- 削除順序: `Section固有resource、common stack、残存確認、cleanup guard`
- 残存確認: `fixtureではAWS削除を実行せず、期待対象だけを確認`
