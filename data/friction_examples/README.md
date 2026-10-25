# 探索実験のデータ形式（会話全体の摩擦）

会話データは JSONL（1行に1会話のJSON）。`//` で始まる行と空行は無視される。

```json
{
  "id": "d001",
  "setting": "大学の同じゼミの友人同士。昼休みに学食で話している。",
  "speakers": {"A": "ユウキ", "B": "ハルカ"},
  "private_info": {
    "A": ["週末に子犬を飼い始めた"],
    "B": ["先週、飼っていた犬が亡くなった"]
  },
  "turns": [
    {"speaker": "A", "text": "ねえ聞いて！週末に子犬をお迎えしたんだ！"},
    {"speaker": "B", "text": "へえ、そうなんだ。"}
  ],
  "human_label": {
    "friction": true,
    "severity": 2,
    "friction_turns": [1],
    "causes": ["private_context_unknown"],
    "annotator": "self",
    "perceived_by": {"A": false, "B": true}
  },
  "source": "self-made",
  "notes": ""
}
```

| 項目 | 必須 | 意味 |
|---|---|---|
| `id` | ○ | 会話ID（重複不可） |
| `setting` | | 両者が共有している状況。条件 `setting: omit` のときは伏せられる |
| `speakers` | ○ | AとBの表示名。性別などの手がかりが結果に影響しないよう、中立的な名前がおすすめ |
| `private_info` | | 片方だけが知る情報。条件 `private_info` に応じてプロンプトに入る |
| `turns` | ○ | 発話の列。ターン番号は1から数える |
| `human_label` | | 人間が付けた正解。ないと妥当性の指標（正解率など）は計算されない |
| `human_label.severity` | | 0=なし、1=軽い違和感、2=明らかな気まずさ・不快、3=深刻 |
| `human_label.causes` | | `configs/friction/taxonomy.yaml` のID |
| `human_label.perceived_by` | | 視点別の正解。A視点の条件はAの、B視点の条件はBのラベルと比べる |
| `source` | | データの出所（コーパス名、自作など） |

## フォルダ

- `sample_dialogues.jsonl` … 動作確認用の架空の会話（8件）。ラベルは環境作成時に付けた仮のもので、**研究データとして使わないこと**。
- 実データは `data/raw/`（元データ）と `data/processed/`（この形式に変換したもの）に置くことをおすすめする。個人が特定できる会話は `.gitignore` で Git から除外してある。

## ラベル付けのコツ

- ラベルを付ける人は、できれば2人以上にして一致度（κ係数）を報告する。
- 「Aから見て」「Bから見て」を分けて付けると、視点条件の評価ができる。
- 実際の会話の当事者に、あとから「どこで引っかかったか」を聞けると、最も強い正解データになる。
