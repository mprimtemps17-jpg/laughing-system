"""人間による独立判定の支援。

1. export: 評価者ごとの評価票（.xlsx は workbook.py、.csv は Excel用 UTF-8 BOM）を作る。場面ID・変種・作成意図ラベルは含めない
2. import: 記入済みの評価票を読み、データの human_labels に取り込む
3. agreement: 評価者間の一致率・κ・不一致例を出し、全員一致の例だけ gold_label の候補にする
"""

from __future__ import annotations

import csv
import random
from itertools import combinations
from pathlib import Path

import pandas as pd
from sklearn.metrics import cohen_kappa_score

from .items import LABELS, CareItem, render_context, save_items

SHEET_COLUMNS = ["提示順", "id", "文脈", "対象発言（A）", "判定", "根拠となる箇所", "理由・迷った点"]


def sheet_id(item_id: str) -> str:
    """評価票に載せる中立的なID。元のID（T001-3 など）は変種の番号が答えの手がかりになるため見せない。"""
    import hashlib

    return "Q" + hashlib.sha1(f"frictionlab:{item_id}".encode()).hexdigest()[:5].upper()


def presentation_order(items: list[CareItem], seed: int) -> list[CareItem]:
    """乱数の種で並べ替え、同じ場面の変種がなるべく連続しないようにする。"""
    rng = random.Random(seed)
    pool = items[:]
    rng.shuffle(pool)
    ordered: list[CareItem] = []
    while pool:
        last = ordered[-1].scene_id if ordered else None
        idx = next((i for i, it in enumerate(pool) if it.scene_id != last), 0)
        ordered.append(pool.pop(idx))
    return ordered


def export_sheet(items: list[CareItem], out_csv: str | Path, seed: int = 0) -> Path:
    out_csv = Path(out_csv)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    ordered = presentation_order(items, seed)
    with out_csv.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(SHEET_COLUMNS)
        for i, it in enumerate(ordered, 1):
            w.writerow([i, sheet_id(it.id), render_context(it), it.target, "", "", ""])
    # 提示順の記録（評価者には渡さない）
    out_csv.with_suffix(".order.txt").write_text(
        f"seed={seed}\n" + " → ".join(f"{it.id}({sheet_id(it.id)})" for it in ordered) + "\n", encoding="utf-8"
    )
    return out_csv


def import_sheet(items: list[CareItem], sheet: str | Path, annotator: str) -> tuple[list[CareItem], list[str]]:
    if str(sheet).endswith(".xlsx"):
        df = pd.read_excel(sheet, sheet_name="評価票", dtype=str).fillna("").rename(columns={"ID": "id"})
    else:
        df = pd.read_csv(sheet, encoding="utf-8-sig", dtype=str).fillna("")
    by_id = {it.id: it for it in items} | {sheet_id(it.id): it for it in items}
    problems = []
    for _, row in df.iterrows():
        it = by_id.get(row["id"])
        label = row["判定"].strip()
        if it is None:
            problems.append(f"id {row['id']} はデータにありません")
            continue
        if not label:
            problems.append(f"{row['id']}: 判定が空欄です")
            continue
        if label not in LABELS:
            problems.append(f"{row['id']}: 判定 '{label}' は {LABELS} のどれでもありません")
            continue
        it.human_labels[annotator] = label
        it.human_notes[annotator] = {"evidence": row.get("根拠となる箇所", ""), "reason": row.get("理由・迷った点", "")}
    return items, problems


def agreement(items: list[CareItem], threshold: float = 0.8) -> tuple[str, pd.DataFrame]:
    annotators = sorted({a for it in items for a in it.human_labels})
    lines = [f"評価者: {', '.join(annotators) or '（なし）'}"]
    for a, b in combinations(annotators, 2):
        both = [it for it in items if a in it.human_labels and b in it.human_labels]
        if not both:
            continue
        ya = [it.human_labels[a] for it in both]
        yb = [it.human_labels[b] for it in both]
        agree = sum(x == y for x, y in zip(ya, yb)) / len(both)
        kappa = cohen_kappa_score(ya, yb) if len(set(ya) | set(yb)) > 1 else float("nan")
        flag = "" if agree >= threshold else f"  ← {threshold:.0%} 未満：件数を増やす前に基準を見直す目安"
        lines.append(f"- {a} vs {b}: 一致率 {agree:.1%}（{len(both)}件）, κ = {kappa:.3f}{flag}")
        ct = pd.crosstab(pd.Series(ya, name=a), pd.Series(yb, name=b))
        lines.append(f"\n（行: {a} / 列: {b}）\n" + ct.to_markdown() + "\n")

    rows = []
    for it in items:
        labs = set(it.human_labels.values())
        rows.append({
            "id": it.id, "scene_id": it.scene_id, "n_annotators": len(it.human_labels),
            "labels": " / ".join(f"{k}:{v}" for k, v in sorted(it.human_labels.items())),
            "unanimous": len(it.human_labels) >= 2 and len(labs) == 1,
            "candidate_gold": next(iter(labs)) if len(labs) == 1 and len(it.human_labels) >= 2 else "",
        })
    df = pd.DataFrame(rows)
    n_dis = int(((df.n_annotators >= 2) & ~df.unanimous).sum())
    lines.append(f"\n全員一致 {int(df.unanimous.sum())} 件 / 不一致 {n_dis} 件。不一致の例は理由を記録して協議する。")
    return "\n".join(lines), df


def write_gold(items: list[CareItem], table: pd.DataFrame, out_path: str | Path) -> int:
    """全員一致（2人以上）の例だけ gold_label を設定して保存する。既存の gold_label は上書きしない。"""
    cand = dict(zip(table.id, table.candidate_gold))
    n = 0
    for it in items:
        if it.gold_label is None and cand.get(it.id):
            it.gold_label = cand[it.id]
            n += 1
    save_items(items, out_path)
    return n
