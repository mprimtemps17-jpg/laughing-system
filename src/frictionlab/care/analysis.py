"""主実験の集計（研究設計 v0.2 の「何を計算し、どこまで言えるか」に対応）。

- 主指標：Aが知っている例（正解が あり/なし）の正解数／対象数
- 知識の誤帰属：Aが知らない例（正解が 判定対象外）を「あり」とした数
- 組全体の一貫性：場面内の全変種を正解した場面数
- 対応する正誤の変化：条件ペアごとの 両方正解／片方のみ正解／両方不正解（正確McNemar検定は参考値）
- 保留・形式違反は正解に数えず、件数を示す
- 予備（pilot）と評価（eval）は合算しない
"""

from __future__ import annotations

import json
from collections import Counter
from itertools import combinations
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yaml
from scipy.stats import binomtest
from sklearn.metrics import f1_score

from .config import CONDITIONS, CareConfig
from .items import EVAL_LABELS, LABELS, load_items

ERROR = "形式違反・エラー"
SERIES_COLOR = "#2a78d6"
TEXT_SECONDARY = "#52514e"
SURFACE = "#fcfcfb"


def load_care_run(run_dir: Path) -> tuple[CareConfig, pd.DataFrame, pd.DataFrame]:
    cfg = CareConfig.model_validate(yaml.safe_load((run_dir / "config.yaml").read_text(encoding="utf-8")))
    latest: dict[str, dict] = {}
    for line in (run_dir / "judgments.jsonl").read_text(encoding="utf-8").splitlines():
        rec = json.loads(line)
        prev = latest.get(rec["key"])
        if prev is None or prev.get("error") is not None or rec.get("error") is None:
            latest[rec["key"]] = rec
    rows = []
    for r in latest.values():
        fin = (r.get("final") or {}).get("parsed") or {}
        rows.append({
            "item_id": r["item_id"], "condition": r["condition"], "repeat": r["repeat"],
            "pred": r.get("label") if r.get("error") is None else ERROR,
            "error": r.get("error"), "reason": fin.get("reason"),
            "evidence": " / ".join(fin.get("evidence", [])),
            "organized": json.dumps((r.get("stage1") or {}).get("parsed"), ensure_ascii=False)
            if r.get("stage1") else "",
            "elapsed_sec": r.get("elapsed_sec"),
            "input_tokens": sum((r.get(s) or {}).get("usage", {}).get("input_tokens", 0) for s in ("stage1", "final")),
            "output_tokens": sum((r.get(s) or {}).get("usage", {}).get("output_tokens", 0) for s in ("stage1", "final")),
        })
    judg = pd.DataFrame(rows)
    items = pd.DataFrame([
        {"item_id": it.id, "scene_id": it.scene_id, "variant": it.variant, "split": it.split,
         "gold_label": it.gold_label, "intended_label": it.intended_label}
        for it in load_items(run_dir / "data.jsonl")
    ])
    return cfg, judg, items


def _majority(labels: list[str]) -> str:
    c = Counter(labels).most_common()
    if len(c) > 1 and c[0][1] == c[1][1]:
        return "不一致"
    return c[0][0]


def item_predictions(judg: pd.DataFrame, items: pd.DataFrame, use_intended: bool) -> pd.DataFrame:
    g = judg.groupby(["item_id", "condition"]).agg(
        pred=("pred", lambda s: _majority(list(s))),
        n_runs=("pred", "size"),
        consistent=("pred", lambda s: s.nunique() == 1),
    ).reset_index()
    df = g.merge(items, on="item_id", how="left")
    df["gold"] = df["gold_label"]
    if use_intended:
        df["gold"] = df["gold"].fillna(df["intended_label"])
    df["evaluated"] = df["gold"].isin(EVAL_LABELS)
    df["correct"] = df["evaluated"] & (df["pred"] == df["gold"])
    return df


def condition_metrics(df: pd.DataFrame, judg: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (split, cond), g in df.groupby(["split", "condition"]):
        known = g[g.gold.isin(["あり", "なし"])]
        unknown = g[g.gold == "判定対象外"]
        ev = g[g.evaluated]
        scenes = ev.groupby("scene_id")["correct"].all()
        present = [lab for lab in EVAL_LABELS if (ev.gold == lab).any()]
        jc = judg[(judg.condition == cond) & judg.item_id.isin(g.item_id)]
        rows.append({
            "split": split, "condition": cond, "label": CONDITIONS[cond]["label"],
            "known_correct": int(known.correct.sum()), "known_n": len(known),
            "known_acc": known.correct.mean() if len(known) else np.nan,
            "unknown_correct": int(unknown.correct.sum()), "unknown_n": len(unknown),
            "misattribution": int((unknown.pred == "あり").sum()),
            "macro_f1": f1_score(ev.gold, ev.pred, labels=present, average="macro", zero_division=0)
            if len(ev) else np.nan,
            "scenes_all_correct": int(scenes.sum()), "scenes_n": len(scenes),
            "pred_hold": int((g.pred == "保留").sum()), "pred_error": int((g.pred == ERROR).sum()),
            "gold_hold_excluded": int((g.gold == "保留").sum()),
            # v0.1 の「判断保留」など、v0.2 の4ラベル以外の正解（集計から除外）
            "gold_other_excluded": int((g.gold.notna() & ~g.gold.isin(LABELS)).sum()),
            "no_gold": int(g.gold.isna().sum()),
            "inconsistent_items": int((~g.consistent).sum()),
            "mean_sec": jc.elapsed_sec.mean(),
            "tokens_in": int(jc.input_tokens.sum()), "tokens_out": int(jc.output_tokens.sum()),
        })
    return pd.DataFrame(rows)


def paired_changes(df: pd.DataFrame, conditions: list[str]) -> pd.DataFrame:
    rows = []
    for split, g in df[df.evaluated].groupby("split"):
        pv = g.pivot(index="item_id", columns="condition", values="correct")
        for x, y in combinations(conditions, 2):
            if x not in pv or y not in pv:
                continue
            p = pv[[x, y]].dropna().astype(bool)
            only_x, only_y = int((p[x] & ~p[y]).sum()), int((~p[x] & p[y]).sum())
            rows.append({
                "split": split, "pair": f"{x} vs {y}", "n": len(p),
                "both_correct": int((p[x] & p[y]).sum()), "only_first": only_x,
                "only_second": only_y, "both_wrong": int((~p[x] & ~p[y]).sum()),
                "mcnemar_p": binomtest(only_x, only_x + only_y, 0.5).pvalue if only_x + only_y else 1.0,
            })
    return pd.DataFrame(rows)


def confusion(df: pd.DataFrame) -> pd.DataFrame:
    cols = list(LABELS) + ["不一致", ERROR]
    out = []
    for (split, cond), g in df[df.gold.notna()].groupby(["split", "condition"]):
        ct = pd.crosstab(g.gold, g.pred).reindex(columns=cols, fill_value=0)
        ct.insert(0, "condition", cond)
        ct.insert(0, "split", split)
        out.append(ct.reset_index().rename(columns={"gold": "正解＼予測"}))
    return pd.concat(out) if out else pd.DataFrame()


def plot(metrics: pd.DataFrame, path: Path) -> None:
    plt.rcParams["font.family"] = ["IPAGothic", "DejaVu Sans"]
    splits = list(metrics.split.unique())
    fig, axes = plt.subplots(1, len(splits), figsize=(5 * len(splits), 0.6 + 0.55 * metrics.condition.nunique()),
                             squeeze=False)
    fig.patch.set_facecolor(SURFACE)
    for ax, sp in zip(axes[0], splits):
        m = metrics[metrics.split == sp]
        y = np.arange(len(m))[::-1]
        ax.barh(y, m.known_acc.fillna(0), height=0.6, color=SERIES_COLOR)
        for yi, (_, r) in zip(y, m.iterrows()):
            ax.text((0 if np.isnan(r.known_acc) else r.known_acc) + 0.01, yi,
                    f"{r.known_correct}/{r.known_n}", va="center", fontsize=9, color=TEXT_SECONDARY)
        ax.set_yticks(y, m.label, fontsize=9)
        ax.set_xlim(0, 1.15)
        ax.set_title(f"既知の例の正解率（{sp}）", fontsize=11, loc="left")
        ax.set_facecolor(SURFACE)
        for s in ("top", "right", "left"):
            ax.spines[s].set_visible(False)
        ax.tick_params(axis="y", length=0)
        ax.tick_params(axis="x", colors=TEXT_SECONDARY, labelsize=8)
        ax.grid(axis="x", color="#e6e5e0", linewidth=0.8)
        ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)


def _md(df: pd.DataFrame) -> str:
    return "（該当なし）" if df.empty else df.to_markdown(index=False, floatfmt=".3f")


def analyze_care(run_dir: str | Path, use_intended: bool = False) -> Path:
    run_dir = Path(run_dir)
    cfg, judg, items = load_care_run(run_dir)
    out = run_dir / "analysis"
    out.mkdir(exist_ok=True)

    if not use_intended and items.gold_label.isna().all():
        print("[注意] 人間の合意ラベル（gold_label）がありません。作成意図のラベルで仮に集計するには "
              "--use-intended を付けてください。")
    df = item_predictions(judg, items, use_intended)
    metrics = condition_metrics(df, judg)
    pairs = paired_changes(df, cfg.conditions)
    conf = confusion(df)

    errs = df[df.evaluated & ~df.correct].merge(
        judg[judg.repeat == 0][["item_id", "condition", "reason", "evidence", "organized"]],
        on=["item_id", "condition"], how="left")
    errs["error_category"] = ""  # ①誰が知るかの取り違え ②制約との照合失敗 ③確認・変更の見落とし ④基準の適用の曖昧さ

    df.to_csv(out / "item_predictions.csv", index=False)
    metrics.to_csv(out / "metrics.csv", index=False)
    pairs.to_csv(out / "paired_changes.csv", index=False)
    conf.to_csv(out / "confusion.csv", index=False)
    errs.to_csv(out / "errors_for_review.csv", index=False, encoding="utf-8-sig")
    if not metrics.empty:
        plot(metrics, out / "known_accuracy.png")

    meta = yaml.safe_load((run_dir / "meta.yaml").read_text(encoding="utf-8"))
    notes = []
    if meta["model"]["backend"] == "mock":
        notes.append("> **mockバックエンドの結果です。判定はランダムで、研究上の意味はありません。**")
    if use_intended:
        notes.append("> **正解ラベルのない例は、作成意図のラベル（intended_label）で代用しています。"
                     "これは人間の判断との一致ではなく、作成者の想定との一致です。**")
    notes.append("> 件数が少ないため、1件の差で割合が大きく動きます。p値は参考値です。"
                 "同じ場面の変種は互いに相関するので、例を独立とはみなせません。")

    report = f"""# 主実験レポート: {cfg.name}

- run: `{run_dir.name}` / モデル: {meta['model']['backend']} {meta['model']['name']}（effort={meta['model']['effort']}）
- プロンプト版: {meta['prompt_version']} / 判定基準: `criteria.md`（{Path(cfg.criteria).name}）/ コード: {meta.get('git_commit') or '不明'}
- 条件: {', '.join(CONDITIONS[c]['label'] for c in cfg.conditions)} / 反復: {cfg.repeats}

{chr(10).join(notes)}

## 1. 条件ごとの結果（split別。予備と評価は合算しない）

![known](known_accuracy.png)

{_md(metrics)}

- `known_correct/known_n`: Aが知っている例（正解が あり/なし）の正解数（主指標）
- `misattribution`: Aが知らない例（正解が 判定対象外）を「あり」とした数（知識の誤帰属）
- `unknown_correct`: Aが知らない例で「判定対象外」と正しく答えた数
- `scenes_all_correct`: 場面内の全変種を正解した場面数
- `pred_hold` / `pred_error`: モデルの「保留」と形式違反・エラーの数（正解に数えない）
- `gold_hold_excluded`: 人間が「保留」とした例（評価から除外）
- `gold_other_excluded`: v0.2 の4ラベル以外の正解を持つ例（v0.1 の「判断保留」など。評価から除外）

## 2. 対応する正誤の変化

{_md(pairs)}

`only_first` は左の条件だけ正解、`only_second` は右の条件だけ正解の件数。

## 3. 混同行列

{_md(conf)}

## 4. 誤り分析

`errors_for_review.csv` に誤答の理由・引用・整理表をまとめた。`error_category` 欄に
①誰が知るかの取り違え ②時間制約との照合失敗 ③確認・変更の見落とし ④判定基準の適用の曖昧さ
を人が記入する。短い理由や整理表は観察できる出力であり、モデル内部の思考過程を直接示すものではない。
"""
    (out / "report.md").write_text(report, encoding="utf-8")
    return out / "report.md"
