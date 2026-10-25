"""実験設定（YAML）の読み込み。

条件は「要因（factor）の組み合わせ」として定義する。
基準条件（baseline）と1つの要因だけが違う条件を並べることで、
その要因の効果を切り出せる（一要因ずつの比較）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator

# 各要因が取りうる値
Viewpoint = Literal["observer", "A", "B"]  # 誰の立場で判定するか
PrivateInfo = Literal["none", "A", "B", "both"]  # 誰の「片方だけが知る情報」を読ませるか
Setting = Literal["include", "omit"]  # 共有状況（setting）を読ませるか

FACTORS = ("viewpoint", "private_info", "setting")


class Condition(BaseModel):
    name: str
    description: str = ""
    viewpoint: Viewpoint = "observer"
    private_info: PrivateInfo = "none"
    setting: Setting = "include"
    # 比較相手の条件名（省略時は baseline）。要因が1つだけ違う条件を指定する
    compare_to: str | None = None

    def factors(self) -> dict[str, str]:
        return {k: getattr(self, k) for k in FACTORS}

    def leaks_other_mind(self) -> bool:
        """A視点なのにBの私的情報を与える、のように視点人物が知り得ない情報を含むか。"""
        if self.viewpoint == "observer":
            return False
        other = "B" if self.viewpoint == "A" else "A"
        return self.private_info in (other, "both")


class ModelConfig(BaseModel):
    backend: Literal["anthropic", "mock"] = "mock"
    name: str = "claude-opus-5-5"
    effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    max_tokens: int = 16000
    use_fallbacks: bool = True  # 安全分類器による拒否時に別モデルで再実行（対応モデルのみ）
    max_workers: int = 4  # 並列リクエスト数


class ExperimentConfig(BaseModel):
    name: str
    data: str
    taxonomy: str = "configs/taxonomy.yaml"
    baseline: str = "baseline"
    conditions: list[Condition]
    model: ModelConfig = Field(default_factory=ModelConfig)
    repeats: int = Field(default=1, ge=1)  # 同一入力を何回判定するか（判定のブレを測る）
    swap_speakers: bool = False  # A/Bのラベルを入れ替えた版も判定する（ラベル順バイアスの確認）
    limit: int | None = None  # 先頭N件だけ使う（試運転用）

    @model_validator(mode="after")
    def _check(self) -> "ExperimentConfig":
        names = [c.name for c in self.conditions]
        if len(names) != len(set(names)):
            raise ValueError("条件名が重複しています")
        if self.baseline not in names:
            raise ValueError(f"baseline '{self.baseline}' が conditions にありません")
        for c in self.conditions:
            if c.compare_to and c.compare_to not in names:
                raise ValueError(f"条件 '{c.name}' の compare_to '{c.compare_to}' がありません")
        return self

    def condition(self, name: str) -> Condition:
        return next(c for c in self.conditions if c.name == name)

    def reference_of(self, cond: Condition) -> str:
        return cond.compare_to or self.baseline

    def diff_from_reference(self, cond: Condition) -> dict[str, tuple[str, str]]:
        """比較相手の条件との違い {要因: (比較相手の値, この条件の値)}。"""
        base = self.condition(self.reference_of(cond)).factors()
        return {k: (base[k], v) for k, v in cond.factors().items() if base[k] != v}


class Cause(BaseModel):
    id: str
    label: str
    description: str
    source: str = ""


def load_experiment(path: str | Path) -> ExperimentConfig:
    with Path(path).open(encoding="utf-8") as f:
        return ExperimentConfig.model_validate(yaml.safe_load(f))


def load_taxonomy(path: str | Path) -> list[Cause]:
    with Path(path).open(encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return [Cause.model_validate(c) for c in raw["causes"]]


def config_warnings(cfg: ExperimentConfig) -> list[str]:
    """実験デザイン上の注意点を列挙する（エラーではない）。"""
    warns = []
    for c in cfg.conditions:
        if c.name == cfg.baseline:
            continue
        ref = cfg.reference_of(c)
        diff = cfg.diff_from_reference(c)
        if len(diff) == 0:
            warns.append(f"条件 '{c.name}' は比較相手 '{ref}' と要因が同じです")
        elif len(diff) > 1:
            warns.append(
                f"条件 '{c.name}' は比較相手 '{ref}' と {len(diff)} 個の要因が異なります "
                f"({', '.join(diff)})。差が出てもどの要因の効果か切り分けられません"
            )
        if c.leaks_other_mind():
            warns.append(
                f"条件 '{c.name}' は {c.viewpoint} の視点なのに、{c.viewpoint} が知り得ない情報を与えています"
                "（意図的な操作でなければ見直してください）"
            )
    return warns
