# friction-lab：会話の配慮不足をLLMで判定する実験環境

## この環境でできること

| 部分 | 内容 | コマンド |
|---|---|---|
| **主実験**（研究設計 v0.2） | Aの対象発言1つについて、既知の制約を反映しない配慮不足を判定する。A 直接判定 / B 人物別の知識整理→判定 / C 一般的な整理→判定 を比較する | `frictionlab care ...` |
| **人間評価** | 暫定ラベルを含まない評価票の作成、記入済み票の取り込み、評価者間の一致度（κ）、全員一致の例の正解化 | `frictionlab human ...` |
| **会話の生成** | 3変種（既知で衝突／既知で適合／未知で衝突）の会話を、テンプレート（API不要）またはLLMで大量に作る | `frictionlab gen ...` |
| **探索実験** | 会話全体の摩擦を、視点（第三者／A／B）や私的情報の条件を変えて判定する（拡張用） | `frictionlab friction ...` |

研究設計と、この環境の対応は [docs/research_design.md](docs/research_design.md)、先行研究との対応は [docs/literature.md](docs/literature.md) にまとめてある。

## セットアップ

```bash
cd friction-lab
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest -q            # 17 passed なら準備完了
```

以下、`python -m frictionlab` を `fl` と略す（`alias fl="python -m frictionlab"` とすると便利）。

## 1. 主実験を動かす

```bash
fl care validate    configs/care/pilot.yaml                 # データと呼び出し回数の確認
fl care show-prompt configs/care/pilot.yaml --item P1-1 --condition B_knowledge   # 送る文面の確認
fl care run         configs/care/pilot.yaml                 # 実行 → results/<日時>_<名前>/
fl care analyze     results/<run> --use-intended            # 集計 → results/<run>/analysis/report.md
```

`configs/care/pilot.yaml` は **mock**（ランダムな判定を返すモード）で、料金をかけずに一通り試せる。実際のLLMで行うには次のどちらかを使う。

| 設定ファイル | 方法 |
|---|---|
| `configs/care/pilot_claude.yaml` | Claude API。`export ANTHROPIC_API_KEY=...` が必要 |
| `configs/care/pilot_manual.yaml` | **API不要**。`results/<run>/manual/*.prompt.md` をChatGPTやClaudeの新しいチャットに貼り、返ってきたJSONを同名の `*.response.txt` に保存して `--resume results/<run>` で再実行する（B・Cは2段階なので2回） |

- `--use-intended` は、人間の正解（`gold_label`）がない例を作成意図のラベルで仮に集計するオプション。レポートにもその旨が明記される。人間の判定がそろったら外す。
- 途中で止まった・エラーが出た場合は `--resume results/<run>` で続きから実行できる（完了済みは飛ばす）。

### 集計される指標（v0.2 第7節に対応）

| 指標 | 意味 |
|---|---|
| `known_correct / known_n` | Aが知っている例（正解が あり/なし）の正解数（主指標） |
| `misattribution` | Aが知らない例（正解が 判定対象外）を「あり」とした数（知識の誤帰属） |
| `scenes_all_correct` | 場面内の全変種を正解した場面数 |
| 対応する正誤の変化 | 条件ペアごとの 両方正解／片方のみ正解／両方不正解（McNemar検定は参考値） |
| 保留・形式違反 | 正解に数えず、件数を報告 |
| `errors_for_review.csv` | 誤答の理由・引用・整理表。誤りの種類（①〜④）を人が記入する欄つき |

予備（pilot）と評価（eval）は常に分けて集計し、合算しない。

## 2. 人間による独立判定

```bash
fl human export    data/care/v0.2_pilot.jsonl --out human_eval/sheet_本人.csv --seed 1
fl human export    data/care/v0.2_pilot.jsonl --out human_eval/sheet_協力者.csv --seed 2
#   → Excelで開いて「判定」列に あり/なし/判定対象外/保留 を記入（根拠・迷った点も）
fl human import    data/care/v0.2_pilot.jsonl human_eval/sheet_本人.csv   --annotator 本人
fl human import    data/care/v0.2_pilot.jsonl human_eval/sheet_協力者.csv --annotator 協力者
fl human agreement data/care/v0.2_pilot.jsonl --table human_eval/agreement.csv
fl human agreement data/care/v0.2_pilot.jsonl --write-gold data/care/v0.2_pilot.jsonl   # 全員一致の例だけ正解を確定
```

- 評価票には場面ID・変種・作成意図ラベルを含めない。評価者には評価票と判定基準（`configs/care/criteria_v0.2_time.md`）だけを渡す。
- 一致率が80%未満なら、件数を増やす前に基準を見直す目安を表示する（v0.2 第6節）。
- 不一致の例は自動で正解にしない。協議して決めたら、データの `gold_label` に手で書く。

### 回答サイト（Excelの代わり）

```bash
fl human survey      # → human_eval/survey/index.html（予備6件＋本番24件）
```

claude.ai の Artifact として公開して使う。回答者は名前を入れて1問ずつ答え、回答は自動保存される（途中再開可）。
全件を答え終えると、ほかの回答者（研究者本人を含む）の判定・理由・一致率が見られる。
保存先の規則：各回答者は自分の回答だけを書け、回答途中のデータは研究者だけが読める。完了した回答だけが比較用に公開される。
回答者が共有設定で「Contributor（使用可）」以上でないと保存できないため、その場合は完了画面の「回答コード」を研究者に送ってもらう。

## 3. 会話を生成する

```bash
fl gen plan configs/gen/time_eval_template.yaml    # どの組み合わせで作るかを確認
fl gen run  configs/gen/time_eval_template.yaml    # → data/generated/time_eval_template.jsonl と .report.md
fl gen show data/generated/time_eval_template.jsonl --scene T001
```

| 設定ファイル | 内容 |
|---|---|
| `configs/gen/time_eval_template.yaml` | v0.2 の評価用「別の8場面×3変種＝24件」の候補（予定調整）。予備と同じ活動（通話・打合せ）は使わない |
| `configs/gen/mixed_template.yaml` | 予定・予算・食事・手段・前提知識の5種類×30場面＋境界対照（制約の解消）＝102件 |
| `configs/gen/llm_care.yaml` | Claudeに場面を作らせる。種類は自由に書ける（例：「家事の分担」）。`backend: manual` でAPIなしでも可 |
| `configs/gen/llm_friction.yaml` | 探索実験用に、私的な事情を含む日常会話を作らせる |

組み合わせる要素（設定ファイルで選べる）：

- **制約の種類**: 予定 / 予算 / 食事 / 手段・アクセス / 前提知識（LLMなら自由）
- **関係**: 友人、ゼミ、サークル、ルームメイト、バイト先、研究室の先輩後輩、グループワーク
- **Aが知る経路**: 会話で直接 / 前日のグループチャット / 第三者経由で聞いて確認
- **Aが知らない経路**: Bだけが知る / Aの不在中に話された / Bの手帳にだけある
- **発言の形**: 決定 / 断定的な提案
- **口調**: くだけた / 丁寧（親しい関係では自動的にくだけた口調）
- **変種**: 既知で衝突（あり）/ 既知で適合（なし）/ 未知で衝突（判定対象外）/ 制約が後から解消（なし）

生成物は自動点検（発言数、露骨な手掛かり語、①③の対象発言が同一か、似すぎた場面がないか）を通ったものだけが保存される。**作成意図のラベルは正解ではない**ので、実験の前に人間が独立に判定すること。

## 4. 探索実験（会話全体の摩擦）

最初に検討した「視点・私的情報の条件を変えて会話全体の摩擦を判定する」実験。将来の拡張（感情・価値観を含む会話）用に残してある。

```bash
fl friction validate configs/friction/experiment.yaml
fl friction run      configs/friction/experiment.yaml
fl friction analyze  results/<run>
```

## フォルダ構成

```
friction-lab/
├── configs/
│   ├── care/      主実験の設定と判定基準（criteria_v0.2_time.md, criteria_v0.3_general_draft.md）
│   ├── gen/       会話生成の設定
│   └── friction/  探索実験の設定と要因分類
├── data/
│   ├── care/                v0.2 予備6例（P1・P2）と v0.1 開発用20件（D01〜D20）
│   ├── generated/           生成した会話（作成意図ラベル付き。正解ではない）
│   └── friction_examples/   探索実験用の架空の会話8件
├── docs/          研究設計と環境の対応、先行研究ノート
├── src/frictionlab/
│   ├── llm.py     LLMの呼び出し（anthropic / manual / mock）
│   ├── care/      主実験（データ形式・プロンプト・実行・集計・人間評価）
│   ├── gen/       会話生成（計画・テンプレート・LLM・自動点検）
│   └── friction/  探索実験
├── tests/
└── results/       実行結果（Git管理外）
```

## 記録と再現性

各実行ディレクトリには、設定・判定基準・データのコピー、モデル名と設定、プロンプトの版（`care-v0.2.0` など）、Gitのコミット、実行順が保存される。各判定には、第1段階（整理表）と最終判定の生の出力、応答したモデル、所要時間、トークン数が残る。整理表に誤りがあっても修正せずに保存する（v0.2 第5節）。

**判定基準やプロンプトを変えたら**、`src/frictionlab/care/prompts.py` の `PROMPT_VERSION` を上げ、古い結果と混ぜずに比べること。
