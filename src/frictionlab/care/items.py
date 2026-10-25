"""判定対象の例（item）の形式と読み書き。形式の説明は data/care/README.md を参照。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

# v0.2 のラベル。モデルの出力もこの4つから選ぶ
LABELS = ("あり", "なし", "判定対象外", "保留")
# 正誤を評価する3クラス（「保留」は人間が付けても評価から外し、件数だけ報告する）
EVAL_LABELS = ("あり", "なし", "判定対象外")
Label = Literal["あり", "なし", "判定対象外", "保留"]


class Turn(BaseModel):
    speaker: Literal["A", "B", "narration"]  # narration は「その後、〜集まった。」のような地の文
    text: str


class CareItem(BaseModel):
    id: str
    scene_id: str  # 基本場面。同じ場面の変種は同じ scene_id を持ち、予備と評価をまたがない
    variant: str = ""  # known_conflict / known_compatible / unknown_conflict など
    split: Literal["pilot", "eval", "dev"] = "dev"
    domain: str = "time"  # time / budget / access など
    route: str = ""  # 情報伝達の経路（direct / group_chat / absent など）
    scene_signature: str = ""  # 生成器が付ける場面の識別（似た場面を予備と評価に分けないため）
    background: str = ""
    turns: list[Turn] = Field(default_factory=list)
    target: str  # 判定対象となるAの発言

    # 作成者・生成器が意図したラベル。人間の正解ではない
    intended_label: str | None = None
    intended_reason: str = ""
    # 人間の独立判定 {評価者名: ラベル}
    human_labels: dict[str, str] = Field(default_factory=dict)
    human_notes: dict[str, dict] = Field(default_factory=dict)
    # 合意した正解ラベル（人間の判定から確定したもの）
    gold_label: Label | None = None

    version: str = ""
    source: str = ""
    notes: str = ""

    @model_validator(mode="after")
    def _check(self) -> "CareItem":
        for who, lab in self.human_labels.items():
            if lab not in LABELS:
                raise ValueError(f"{self.id}: 評価者 {who} のラベル '{lab}' は {LABELS} のどれでもありません")
        return self


def render_context(item: CareItem) -> str:
    """モデル・評価者に見せる文脈（背景と会話）。ラベルや作成意図は含めない。"""
    parts = []
    if item.background:
        parts.append(f"【背景】\n{item.background}")
    if item.turns:
        lines = [t.text if t.speaker == "narration" else f"{t.speaker}「{t.text}」" for t in item.turns]
        parts.append("【会話】\n" + "\n".join(lines))
    return "\n\n".join(parts)


def load_items(path: str | Path) -> list[CareItem]:
    items, seen = [], set()
    with Path(path).open(encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            try:
                it = CareItem.model_validate(json.loads(line))
            except Exception as e:
                raise ValueError(f"{path}:{lineno}: {e}") from e
            if it.id in seen:
                raise ValueError(f"{path}:{lineno}: id '{it.id}' が重複しています")
            seen.add(it.id)
            items.append(it)
    return items


def save_items(items: list[CareItem], path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with Path(path).open("w", encoding="utf-8") as f:
        for it in items:
            f.write(json.dumps(it.model_dump(exclude_defaults=True), ensure_ascii=False) + "\n")


def check_splits(items: list[CareItem]) -> list[str]:
    """同じ基本場面が予備と評価にまたがっていないかを確認する。"""
    by_scene: dict[str, set[str]] = {}
    for it in items:
        by_scene.setdefault(it.scene_id, set()).add(it.split)
    return [f"場面 {s} が {sorted(v)} にまたがっています" for s, v in by_scene.items() if len(v) > 1]
