# EKS初動対応Runbook

## 基本情報

- 記録時刻: `<UTCまたはJSTの時刻>`
- 症状: `<観察できる症状>`
- 開始時刻: `<判明している時刻。不明なら不明>`
- 影響範囲: `<利用者、namespace、workload>`
- 変更承認者: `<変更が必要な場合の承認者>`

## 観察した事実

- Pod: `<STATUS、RESTARTS、配置Node>`
- Node: `<Ready状態、pressure、taint>`
- Event: `<reason、対象、時刻>`
- Log / Metric: `<時間帯と観察結果>`
- 権限: `<Forbidden、Unauthorized、AccessDeniedの有無>`

## まだ分からないこと

- `<不足している観察または権限>`

## 仮説

- `<事実から考えられる原因。確定と表現しない>`

## 次の安全な確認

1. `<読み取り専用の確認>`
2. `<変更が必要なら実行前の承認条件>`

## エスカレーション条件

- `<影響、時間、権限、安全境界に基づく条件>`

## コストとcleanup

- 課金中の可能性があるresource: `<exact resource名とRegion。account IDやARNは書かない>`
- 所有権を確認した方法: `<stack、tag、作成記録>`
- 削除順序: `<Section固有resource → common → residual確認 → guard>`
- 残存確認: `<確認対象と結果>`
