# 主実験のデータ形式

JSONL（1行に1例）。`//` で始まる行と空行は無視される。

```json
{
  "id": "P1-1",
  "scene_id": "P1",
  "variant": "known_conflict",
  "split": "pilot",
  "domain": "time",
  "route": "direct",
  "scene_signature": "time:通話",
  "background": "AとBは友人で、明日の課題について30分通話する予定を決める。",
  "turns": [
    {"speaker": "B", "text": "今日は18時から22時までバイトで、通話できない"},
    {"speaker": "A", "text": "分かった"},
    {"speaker": "B", "text": "通話の開始時刻を決めよう"}
  ],
  "target": "通話は今日20時開始で決定にするね",
  "intended_label": "あり",
  "intended_reason": "Aが聞いた不参加時間に重なり、確認や調整がない。",
  "human_labels": {"本人": "あり", "協力者": "あり"},
  "gold_label": "あり",
  "version": "v0.2",
  "source": "..."
}
```

| 項目 | 意味 |
|---|---|
| `scene_id` | 基本場面。同じ場面の変種は同じ値。**予備と評価にまたがってはいけない** |
| `variant` | `known_conflict`（①）/ `known_compatible`（②）/ `unknown_conflict`（③）/ `known_updated`（境界対照）など |
| `split` | `pilot`（予備）/ `eval`（評価）/ `dev`（開発用）。集計は split ごとに分ける |
| `route` | Aが知る・知らない経路（`direct`, `group_chat`, `third_party`, `private_only`, `absent`, `memo`） |
| `turns[].speaker` | `A` / `B` / `narration`（「その後、〜集まった。」のような地の文） |
| `target` | 判定対象のAの発言（話者名・かぎかっこなし） |
| `intended_label` | 作成者・生成器が意図したラベル。**正解ではない**。モデルにも評価者にも見せない |
| `human_labels` | 評価者ごとの独立判定（`human import` で入る）。協議前の判定として残す |
| `gold_label` | 協議・合意で確定した正解。集計はこれを使う |

## ファイル

- `v0.2_pilot.jsonl` … 統合記録 第5章の予備6例（P1 通話時刻、P2 ゼミ前の打合せ）。暫定ラベルは `intended_label`。
- `v0.1_dev.jsonl` … 統合記録 第8章の初期20件（D01〜D20）。v0.1 のラベル（判断保留を含む）のまま。
