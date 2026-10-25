"""会話データの読み込みと検証。

データは JSONL（1行 = 1会話）。形式は data/README.md を参照。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

Speaker = Literal["A", "B"]


class Turn(BaseModel):
    speaker: Speaker
    text: str


class HumanLabel(BaseModel):
    """人間（研究者・協力者）が付けた正解ラベル。LLM判定の妥当性を測る基準になる。"""

    friction: bool
    severity: int = Field(ge=0, le=3, default=0)
    friction_turns: list[int] = Field(default_factory=list)  # 1始まりのターン番号
    causes: list[str] = Field(default_factory=list)
    annotator: str = "unknown"
    # 視点別ラベル（任意）: Aから見て/Bから見て摩擦があったか
    perceived_by: dict[Speaker, bool] | None = None


class Dialogue(BaseModel):
    id: str
    setting: str = ""  # 両者が共有している状況（場所・関係性など）
    speakers: dict[Speaker, str]  # 表示名 例: {"A": "ユウキ", "B": "ハルカ"}
    private_info: dict[Speaker, list[str]] = Field(default_factory=dict)  # 片方だけが知る情報
    turns: list[Turn]
    human_label: HumanLabel | None = None
    source: str = "unknown"  # データの出所（example / corpus名 / self-made など）
    notes: str = ""

    @model_validator(mode="after")
    def _check(self) -> "Dialogue":
        if set(self.speakers) != {"A", "B"}:
            raise ValueError(f"{self.id}: speakers には A と B の両方が必要です")
        if len(self.turns) < 2:
            raise ValueError(f"{self.id}: ターンが2つ未満です")
        if self.human_label:
            bad = [t for t in self.human_label.friction_turns if not 1 <= t <= len(self.turns)]
            if bad:
                raise ValueError(f"{self.id}: friction_turns {bad} がターン範囲外です")
        return self


def load_dialogues(path: str | Path) -> list[Dialogue]:
    path = Path(path)
    dialogues: list[Dialogue] = []
    seen: set[str] = set()
    with path.open(encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            try:
                d = Dialogue.model_validate(json.loads(line))
            except Exception as e:  # 行番号付きで分かりやすく
                raise ValueError(f"{path}:{lineno}: {e}") from e
            if d.id in seen:
                raise ValueError(f"{path}:{lineno}: id '{d.id}' が重複しています")
            seen.add(d.id)
            dialogues.append(d)
    return dialogues
