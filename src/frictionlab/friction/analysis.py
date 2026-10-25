"""実行結果の分析。

主な問い:
1. 各条件で、LLMはどれだけ摩擦を検出したか（検出率・強さ）
2. 人間ラベルとどれだけ一致したか（正解率・F1・κ）
3. 基準条件から要因を1つ変えると、判定・正解率はどう変わったか（McNemar検定）
4. 同じ入力を繰り返したとき・A/Bを入れ替えたとき、判定は安定しているか
5. A視点とB視点で判定はどれだけ一致するか（間主観的な一致度）
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yaml
from scipy.stats import binomtest, spearmanr
from sklearn.metrics import cohen_kappa_score, f1_score, precision_score, recall_score

from .config import ExperimentConfig
from .data import load_dialogues

SERIES_COLOR = "#2a78d6"
TEXT_SECONDARY = "#52514e"
SURFACE = "#fcfcfb"


def load_run(run_dir: str | Path) -> tuple[ExperimentConfig, pd.DataFrame, pd.DataFrame]:
    """(設定, 判定ごとの表, 人間ラベルの表) を返す。"""
    run_dir = Path(run_dir)
    cfg = ExperimentConfig.model_validate(
        yaml.safe_load((run_dir / "config.yaml").read_text(encoding="utf-8"))
    )
    # 同じkeyが複数ある場合（エラー後の再実行）は、最後の成功記録を使う
    latest: dict[str, dict] = {}
    for line in (run_dir / "judgments.jsonl").read_text(encoding="utf-8").splitlines():
        rec = json.loads(line)
        prev = latest.get(rec["key"])
        if prev is None or prev.get("error") is not None or rec.get("error") is None:
            latest[rec["key"]] = rec

    rows = []
    for rec in latest.values():
        j = rec.get("judgment") or {}
        rows.append(
            {
                "dialogue_id": rec["dialogue_id"],
                "condition": rec["condition"],
                "repeat": rec["repeat"],
                "swapped": rec["swapped"],
                "error": rec.get("error"),
                "model": rec.get("model"),
                "friction": j.get("friction"),
                "severity": j.get("severity"),
                "caused_by": j.get("caused_by"),
                "causes": j.get("causes", []),
                "friction_turns": j.get("friction_turns", []),
                "rationale": j.get("rationale"),
            }
        )
    judg = pd.DataFrame(rows)

    labels = []
    for d in load_dialogues(run_dir / "data.jsonl"):
        if d.human_label:
            h = d.human_label
            labels.append(
                {
                    "dialogue_id": d.id,
                    "gold_friction": h.friction,
                    "gold_severity": h.severity,
                    "gold_causes": h.causes,
                    "gold_perceived_A": (h.perceived_by or {}).get("A"),
                    "gold_perceived_B": (h.perceived_by or {}).get("B"),
                }
            )
    gold = pd.DataFrame(labels, columns=[
        "dialogue_id", "gold_friction", "gold_severity", "gold_causes",
        "gold_perceived_A", "gold_perceived_B",
    ])
    return cfg, judg, gold


def item_level(judg: pd.DataFrame) -> pd.DataFrame:
    """会話×条件ごとに、繰り返し・入れ替えをまとめる（多数決と平均）。"""
    ok = judg[judg.error.isna()].copy()
    ok["friction"] = ok["friction"].astype(bool)
    g = ok.groupby(["dialogue_id", "condition"])
    items = g.agg(
        n=("friction", "size"),
        friction_rate=("friction", "mean"),
        severity_mean=("severity", "mean"),
    ).reset_index()
    items["friction_vote"] = items["friction_rate"] >= 0.5
    # 全判定が一致したか（繰り返し・入れ替えをまたいだ安定性）
    items["unanimous"] = items["friction_rate"].isin([0.0, 1.0])

    # 入れ替え前後の一致（swap_speakers=true のときのみ意味がある）
    if ok["swapped"].any():
        sw = ok.groupby(["dialogue_id", "condition", "swapped"])["friction"].mean().unstack()
        if True in sw.columns and False in sw.columns:
            same = ((sw[True] >= 0.5) == (sw[False] >= 0.5)).rename("swap_agree").reset_index()
            items = items.merge(same, on=["dialogue_id", "condition"], how="left")
    return items


def _target_gold(cfg: ExperimentConfig, cond_name: str, gold: pd.DataFrame) -> pd.Series:
    """条件の視点に合った正解ラベル。視点別ラベルがあればそれを、なければ全体ラベルを使う。"""
    v = cfg.condition(cond_name).viewpoint
    col = f"gold_perceived_{v}"
    if v in ("A", "B") and col in gold and gold[col].notna().all() and len(gold):
        return gold.set_index("dialogue_id")[col].astype(bool)
    return gold.set_index("dialogue_id")["gold_friction"].astype(bool)


def summarize(cfg: ExperimentConfig, judg: pd.DataFrame, gold: pd.DataFrame, items: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for c in cfg.conditions:
        jc = judg[judg.condition == c.name]
        ic = items[items.condition == c.name]
        row = {
            "condition": c.name,
            **c.factors(),
            "n_judgments": len(jc),
            "error_rate": jc.error.notna().mean() if len(jc) else np.nan,
            "friction_rate": ic.friction_vote.mean() if len(ic) else np.nan,
            "severity_mean": ic.severity_mean.mean() if len(ic) else np.nan,
            "unanimous_rate": ic.unanimous.mean() if len(ic) else np.nan,
        }
        if "swap_agree" in ic:
            row["swap_agree_rate"] = ic.swap_agree.mean()
        if len(gold):
            tg = _target_gold(cfg, c.name, gold)
            m = ic.set_index("dialogue_id").join(tg.rename("gold"), how="inner")
            m = m.join(gold.set_index("dialogue_id")["gold_severity"], how="left")
            if len(m):
                y, p = m["gold"].astype(bool), m["friction_vote"].astype(bool)
                row.update(
                    n_labeled=len(m),
                    accuracy=(y == p).mean(),
                    precision=precision_score(y, p, zero_division=0),
                    recall=recall_score(y, p, zero_division=0),
                    f1=f1_score(y, p, zero_division=0),
                    kappa=cohen_kappa_score(y, p) if y.nunique() > 1 or p.nunique() > 1 else np.nan,
                    severity_spearman=(
                        spearmanr(m["gold_severity"], m["severity_mean"]).statistic
                        if m["severity_mean"].nunique() > 1 and m["gold_severity"].nunique() > 1
                        else np.nan
                    ),
                )
        rows.append(row)
    return pd.DataFrame(rows)


def _mcnemar(a: pd.Series, b: pd.Series) -> tuple[int, int, float]:
    """対応のある2値データの比較（正確McNemar検定）。(a のみ真, b のみ真, p値)"""
    n01 = int((a & ~b).sum())
    n10 = int((~a & b).sum())
    if n01 + n10 == 0:
        return n01, n10, 1.0
    return n01, n10, binomtest(n01, n01 + n10, 0.5).pvalue


def compare_to_reference(cfg: ExperimentConfig, gold: pd.DataFrame, items: pd.DataFrame) -> pd.DataFrame:
    """各条件を比較相手（compare_to、省略時は baseline）と対応のある比較をする。"""
    rows = []
    for c in cfg.conditions:
        if c.name == cfg.baseline:
            continue
        ref = cfg.reference_of(c)
        base = items[items.condition == ref].set_index("dialogue_id")
        ic = items[items.condition == c.name].set_index("dialogue_id")
        common = base.index.intersection(ic.index)
        bv, cv = base.loc[common, "friction_vote"].astype(bool), ic.loc[common, "friction_vote"].astype(bool)
        diff = cfg.diff_from_reference(c)
        b_only, c_only, p = _mcnemar(bv, cv)
        row = {
            "condition": c.name,
            "reference": ref,
            "changed_factors": ", ".join(f"{k}: {v[0]}→{v[1]}" for k, v in diff.items()),
            "n_items": len(common),
            "friction_rate_ref": bv.mean(),
            "friction_rate_cond": cv.mean(),
            "delta_friction_rate": cv.mean() - bv.mean(),
            "flips_to_friction": c_only,
            "flips_to_no_friction": b_only,
            "p_judgment_change": p,
            "delta_severity": (
                ic.loc[common, "severity_mean"] - base.loc[common, "severity_mean"]
            ).mean(),
        }
        if len(gold):
            gb = _target_gold(cfg, ref, gold)
            gc = _target_gold(cfg, c.name, gold)
            lab = common.intersection(gb.index)
            if len(lab):
                corr_b = bv.loc[lab] == gb.loc[lab]
                corr_c = cv.loc[lab] == gc.loc[lab]
                bw, cw, p2 = _mcnemar(corr_b, corr_c)
                row.update(
                    accuracy_ref=corr_b.mean(),
                    accuracy_cond=corr_c.mean(),
                    delta_accuracy=corr_c.mean() - corr_b.mean(),
                    only_ref_correct=bw,
                    only_cond_correct=cw,
                    p_accuracy_change=p2,
                )
        rows.append(row)
    return pd.DataFrame(rows)


def perspective_agreement(cfg: ExperimentConfig, items: pd.DataFrame) -> pd.DataFrame:
    """A視点とB視点の条件の組（他の要因は鏡像）について、判定の一致度を測る。"""
    mirror = {"none": "none", "both": "both", "A": "B", "B": "A"}
    rows = []
    for ca in cfg.conditions:
        if ca.viewpoint != "A":
            continue
        for cb in cfg.conditions:
            if cb.viewpoint == "B" and cb.private_info == mirror[ca.private_info] and cb.setting == ca.setting:
                a = items[items.condition == ca.name].set_index("dialogue_id")
                b = items[items.condition == cb.name].set_index("dialogue_id")
                common = a.index.intersection(b.index)
                if not len(common):
                    continue
                rows.append(
                    {
                        "condition_A": ca.name,
                        "condition_B": cb.name,
                        "n_items": len(common),
                        "agreement": (a.loc[common, "friction_vote"] == b.loc[common, "friction_vote"]).mean(),
                        "mean_abs_severity_gap": (
                            a.loc[common, "severity_mean"] - b.loc[common, "severity_mean"]
                        ).abs().mean(),
                        "only_A_feels": int((a.loc[common, "friction_vote"] & ~b.loc[common, "friction_vote"]).sum()),
                        "only_B_feels": int((~a.loc[common, "friction_vote"] & b.loc[common, "friction_vote"]).sum()),
                    }
                )
    return pd.DataFrame(rows)


def cause_distribution(judg: pd.DataFrame) -> pd.DataFrame:
    """摩擦ありと判定されたものの中で、各要因が挙げられた割合（条件別）。"""
    ok = judg[judg.error.isna() & judg.friction.astype(bool)]
    rows = []
    for cond, g in ok.groupby("condition"):
        cnt = Counter(c for cs in g.causes for c in cs)
        for cause, n in cnt.items():
            rows.append({"condition": cond, "cause": cause, "share": n / len(g), "count": n})
    df = pd.DataFrame(rows, columns=["condition", "cause", "share", "count"])
    return df.pivot_table(index="cause", columns="condition", values="share", fill_value=0.0)


def plot_summary(summary: pd.DataFrame, baseline: str, path: Path) -> None:
    plt.rcParams["font.family"] = ["IPAGothic", "DejaVu Sans"]
    metrics = [("friction_rate", "摩擦ありと判定した割合")]
    if "accuracy" in summary:
        metrics.append(("accuracy", "人間ラベルとの一致率"))
    labels = [f"{c}（基準）" if c == baseline else c for c in summary.condition]
    h = 0.5 + 0.45 * len(summary)
    fig, axes = plt.subplots(1, len(metrics), figsize=(5.2 * len(metrics), h), squeeze=False)
    fig.patch.set_facecolor(SURFACE)
    for ax, (col, title) in zip(axes[0], metrics):
        vals = summary[col].fillna(0).to_numpy()
        y = np.arange(len(vals))[::-1]
        ax.barh(y, vals, height=0.6, color=SERIES_COLOR)
        for yi, v in zip(y, vals):
            ax.text(v + 0.01, yi, f"{v:.2f}", va="center", fontsize=9, color=TEXT_SECONDARY)
        ax.set_yticks(y, labels, fontsize=9)
        ax.set_xlim(0, 1.12)
        ax.set_title(title, fontsize=11, loc="left")
        ax.set_facecolor(SURFACE)
        for s in ("top", "right", "left"):
            ax.spines[s].set_visible(False)
        ax.spines["bottom"].set_color("#c3c2b7")
        ax.tick_params(axis="x", colors=TEXT_SECONDARY, labelsize=8)
        ax.tick_params(axis="y", length=0)
        ax.grid(axis="x", color="#e6e5e0", linewidth=0.8)
        ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)


def _md(df: pd.DataFrame) -> str:
    if df.empty:
        return "（該当なし）"
    return df.to_markdown(index=False, floatfmt=".3f")


def analyze(run_dir: str | Path) -> Path:
    run_dir = Path(run_dir)
    cfg, judg, gold = load_run(run_dir)
    out = run_dir / "analysis"
    out.mkdir(exist_ok=True)

    items = item_level(judg)
    summary = summarize(cfg, judg, gold, items)
    comp = compare_to_reference(cfg, gold, items)
    persp = perspective_agreement(cfg, items)
    causes = cause_distribution(judg)

    judg.to_csv(out / "judgments.csv", index=False)
    items.to_csv(out / "items.csv", index=False)
    summary.to_csv(out / "summary.csv", index=False)
    comp.to_csv(out / "vs_reference.csv", index=False)
    persp.to_csv(out / "perspective.csv", index=False)
    causes.to_csv(out / "causes.csv")
    plot_summary(summary, cfg.baseline, out / "summary.png")

    meta = yaml.safe_load((run_dir / "meta.yaml").read_text(encoding="utf-8"))
    notes = []
    if meta["model"]["backend"] == "mock":
        notes.append("> **mockバックエンドの結果です。判定はランダムで、研究上の意味はありません。**")
    if gold.empty:
        notes.append("> 人間ラベルがないため、正解率などの妥当性指標は計算していません。")
    n_items = judg.dialogue_id.nunique()
    if n_items < 30:
        notes.append(
            f"> 会話数が {n_items} 件と少ないため、p値や差の大きさは参考程度に見てください。"
        )

    report = f"""# 分析レポート: {cfg.name}

- 実行: `{run_dir.name}`
- モデル: {meta['model']['backend']} / {meta['model']['name']}（effort={meta['model']['effort']}）
- プロンプト版: {meta['prompt_version']} / コード: {meta.get('git_commit') or '不明'}
- 会話数: {n_items} / 判定数: {len(judg)}（エラー {int(judg.error.notna().sum())}）
- 繰り返し: {cfg.repeats} 回 / A・B入れ替え: {'あり' if cfg.swap_speakers else 'なし'}

{chr(10).join(notes)}

## 1. 条件ごとの結果

![summary](summary.png)

{_md(summary)}

- `friction_rate`: 会話ごとの多数決で「摩擦あり」となった割合
- `unanimous_rate`: 繰り返し・入れ替えの全判定が一致した会話の割合（判定の安定性）
- `accuracy` / `f1` / `kappa`: 人間ラベルとの一致（視点別ラベルがあればそれを使用）

## 2. 比較相手の条件との比較（要因を1つ変えた効果）

{_md(comp)}

- `reference`: 比較相手の条件（compare_to。省略時は基準条件 {cfg.baseline}）
- `flips_to_friction`: 比較相手では「摩擦なし」→ この条件で「摩擦あり」になった会話数
- `p_judgment_change`: 判定の変化に偏りがあるか（正確McNemar検定）
- `p_accuracy_change`: 正解率の変化が偶然で説明できるか（正確McNemar検定）
- 複数の条件を比べるときは多重比較に注意（条件数が多いほど偶然の有意差が出やすい）

## 3. 視点間の一致（A視点 vs B視点）

{_md(persp)}

## 4. 挙げられた要因の割合（摩擦ありの判定のうち）

{_md(causes.reset_index()) if not causes.empty else '（該当なし）'}
"""
    (out / "report.md").write_text(report, encoding="utf-8")
    return out / "report.md"
