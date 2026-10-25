"""主実験の設定。"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

from ..llm import ModelConfig

ConditionName = Literal["A_direct", "B_knowledge", "C_general"]

# 条件ごとの手順：第1段階の整理の種類（None は整理なし）と呼び出し回数
CONDITIONS: dict[str, dict] = {
    "A_direct": {"organize": None, "calls": 1, "label": "A：直接判定"},
    "B_knowledge": {"organize": "knowledge", "calls": 2, "label": "B：人物別の知識整理→判定"},
    "C_general": {"organize": "general", "calls": 2, "label": "C：一般的な整理→判定"},
}


class CareConfig(BaseModel):
    name: str
    data: str
    criteria: str = "configs/care/criteria_v0.2_time.md"
    conditions: list[ConditionName] = Field(default_factory=lambda: ["A_direct", "B_knowledge"])
    splits: list[Literal["pilot", "eval", "dev"]] | None = None  # 使う split（省略時は全部）
    model: ModelConfig = Field(default_factory=ModelConfig)
    repeats: int = Field(default=1, ge=1)
    limit: int | None = None  # 先頭N件だけ使う（試運転用）


def load_care_config(path: str | Path) -> CareConfig:
    with Path(path).open(encoding="utf-8") as f:
        return CareConfig.model_validate(yaml.safe_load(f))
