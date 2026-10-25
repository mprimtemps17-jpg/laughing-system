# friction-lab：会話の摩擦をLLMで判定し、要因を探る実験環境

## 研究の概要

**問い**: 人どうしの会話で起きる摩擦（すれ違い・配慮不足）は、何が原因で起きるのか。

**方法**:
1. 二人（A・B）の会話ログをLLMに読ませ、摩擦があるかを判定させる（基準条件。先行研究の基本形）
2. 条件を**1つずつ**変えて同じ判定をする（例：片方だけが知る情報を読ませる、本人の視点に立たせる）
3. 判定の変化と、**人間の判断（正解ラベル）との一致度の変化**を比べる。どの情報を与えると人間の感覚に近づくかを調べ、摩擦の要因を推定する

先行研究との対応は [docs/literature.md](docs/literature.md) にまとめてある。

## セットアップ

```bash
cd friction-lab
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest -q            # 6 passed なら準備完了
```

## 使い方（4ステップ）

```bash
# 1. 設定とデータを検査する（LLMを何回呼ぶかも表示される）
python -m frictionlab validate configs/experiment.yaml

# 2. 実際にLLMへ送るプロンプトを確認する
python -m frictionlab show-prompt configs/experiment.yaml --dialogue ex01 --condition pov_B_private

# 3. 実験を実行する（results/<日時>_<名前>/ に全判定が保存される）
python -m frictionlab run configs/experiment.yaml

# 4. 分析する（results/<run>/analysis/report.md と表・グラフができる）
python -m frictionlab analyze results/<run>
```

`configs/experiment.yaml` は **mock（APIを呼ばずにランダムな判定を返すモード）** になっているので、料金をかけずに一通り動かせる。mockの結果に研究上の意味はない。

### Claude API で本番実行する

```bash
export ANTHROPIC_API_KEY=sk-ant-...      # Claude Console で発行したAPIキー
python -m frictionlab validate configs/experiment_claude.yaml   # 呼び出し回数を確認
python -m frictionlab run configs/experiment_claude.yaml        # まず limit: 3 で試運転
```

- モデルは `claude-opus-5-5`（設定の `model.name` で変更できる）。判定のJSONは構造化出力で形式を保証している。
- 途中で止まったり一部がエラーになったりしたら、`--resume results/<run>` を付けて同じコマンドを実行すると、完了済みの判定を飛ばして続きから実行できる。
- 費用の目安：1回の判定は入力約1,500トークン＋出力（思考を含む）数千トークン。`validate` で表示される回数 × 1回あたりの費用で見積もり、少数で試してから全件を実行すること。

## 条件の作り方

条件は3つの**要因**の組み合わせで決まる。

| 要因 | 値 | 意味 |
|---|---|---|
| `viewpoint` | `observer` / `A` / `B` | 第三者として判定するか、本人の立場に立つか |
| `private_info` | `none` / `A` / `B` / `both` | 誰の「片方だけが知る情報」を読ませるか |
| `setting` | `include` / `omit` | 二人が共有する状況の説明を読ませるか |

```yaml
- name: pov_B_private
  description: B本人の視点 + Bだけが知る情報
  viewpoint: B
  private_info: B
  compare_to: pov_B     # 比べる相手。要因が1つだけ違う条件を指定する（省略時は baseline）
```

- 比べる相手と2つ以上の要因が違うと、`validate` が警告を出す（差が出ても、どの要因の効果か分からないため）。
- 新しい要因（例：会話の一部だけを見せる、2次の信念を問う）を足すときは、`config.py` の `FACTORS` と `prompts.py` の `build_prompt` に追加する。

## 分析で出てくるもの（`results/<run>/analysis/`）

| ファイル | 内容 |
|---|---|
| `report.md` | まとめレポート |
| `summary.csv` / `summary.png` | 条件ごとの摩擦検出率、人間ラベルとの一致（正解率・F1・κ）、判定の安定性 |
| `vs_reference.csv` | 比較相手の条件との差（要因を1つ変えた効果）とMcNemar検定 |
| `perspective.csv` | A視点とB視点の判定の一致度（「Aだけが感じた摩擦」など） |
| `causes.csv` | 条件ごとに、LLMが挙げた要因の割合 |
| `items.csv` / `judgments.csv` | 会話ごと・判定ごとの詳細（判定理由 `rationale` を含む） |

## フォルダ構成

```
friction-lab/
├── configs/
│   ├── experiment.yaml          # 試運転用（mock）
│   ├── experiment_claude.yaml   # 本番用（Claude API）
│   └── taxonomy.yaml            # 摩擦の要因分類（先行研究に対応）
├── data/
│   ├── README.md                # データ形式
│   └── examples/                # 動作確認用の架空の会話8件
├── docs/literature.md           # 先行研究ノート
├── src/frictionlab/
│   ├── data.py                  # データの読み込み・検証
│   ├── config.py                # 条件・設定
│   ├── prompts.py               # プロンプトの組み立て
│   ├── llm.py                   # LLMの呼び出し（anthropic / mock）
│   ├── runner.py                # 実験の実行・記録
│   ├── analysis.py              # 分析・レポート
│   └── cli.py                   # コマンド
├── tests/
└── results/                     # 実行結果（Git管理外）
```

## 再現性のために自動で記録されること

各実行ディレクトリには、そのときの設定（`config.yaml`）、要因分類、データのコピー、モデル名、プロンプトの版、Gitのコミットが保存される。各判定には、送ったプロンプトのハッシュ、実際に応答したモデル、生の出力が残る。**プロンプトや要因分類を変えたら、`prompts.py` の `PROMPT_VERSION` を上げ、古い結果と混ぜずに比べること。**

## 研究を進めるうえでの注意

1. **人間ラベルが研究の要**：条件間でLLMの判定が変わっても、それだけでは「人間の摩擦の原因」とは言えない。人間の判断との一致がどう変わるかを示すこと。
2. **サンプル数**：8件ではほぼ何も言えない。条件の差を検出するには、少なくとも数十〜百件程度の会話が必要になる。
3. **判定のブレとバイアス**：LLMの判定は毎回少しずつ変わり、A/Bのラベル順にも影響されうる。`repeats` と `swap_speakers` で確認する。
4. **多重比較**：条件を増やすほど偶然の有意差が出やすい。事前に主な比較を決めておく。
5. **データ倫理**：実際の会話を使う場合は、同意の取得と匿名化を行い、所属機関の倫理審査の要否を確認する。
