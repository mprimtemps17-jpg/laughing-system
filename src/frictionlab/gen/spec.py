"""生成の設定と、場面の仕様（どの組み合わせを何件作るか）の計画。"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

from ..llm import ModelConfig

ROUTE_KNOWN_DESC = {
    "direct": "Bが会話の中でAに直接伝え、Aが応答している",
    "group_chat": "前日にBがグループチャットに書き込み、Aが返信している（背景に書く）",
    "third_party": "Aが第三者Cから聞いた内容をBに確認し、Bが認めている",
}
ROUTE_UNKNOWN_DESC = {
    "private_only": "Bだけが事情を知り、Aには伝えておらず、Aが別の経路で知ったこともない（背景に明記）",
    "absent": "Aが席を外している間に、Bが2人の予定とは関係のない第三者Cに話した。Aはその場にいなかった（背景に明記。CがAに伝える立場にない理由も書く）",
    "memo": "Bの個人的なメモ・手帳にだけ書かれていて、Aは見ていない（背景に明記）",
}
DOMAIN_DESC = {
    "time": "予定調整（時刻・時間帯の制約）",
    "budget": "お金（出せる金額の上限）",
    "dietary": "食事（アレルギーや食べられないもの）",
    "access": "手段・アクセス（権限、道具、鍵などがない）",
    "prior_knowledge": "前提知識（話の前提となる出来事を相手が知らない）",
    "sharing_scope": "話してよい範囲（秘密にしてほしい話）",
}
VARIANT_DESC = {
    "known_conflict": "Aが制約を知っており、対象発言が制約に反する（確認・調整なしに提案・決定・依頼する）",
    "known_compatible": "known_conflict と同じ背景・会話で、対象発言だけを制約に合うもの（避ける・確認する）に変える",
    "unknown_conflict": "Bだけが制約を知っていてAは知らない。対象発言は known_conflict と一字一句同じ",
    "known_updated": "Aは制約を知っていたが、Bが後から制約の解消をAに伝えている。対象発言は known_conflict と同じ",
}


class GenConfig(BaseModel):
    name: str
    output: str  # 生成データの保存先（.jsonl）
    method: Literal["template", "llm"] = "template"
    format: Literal["care", "friction"] = "care"  # care=主実験の形式, friction=探索実験の形式（llmのみ）
    seed: int = 0
    id_prefix: str = "G"
    split: Literal["pilot", "eval", "dev"] = "dev"
    n_scenes: int = 8

    domains: list[str] = Field(default_factory=lambda: ["time"])
    relationships: list[str] = Field(default_factory=lambda: [
        "friends", "seminar", "club", "roommates", "part_time", "lab_junior_A", "lab_senior_A", "group_work"])
    routes_known: list[str] = Field(default_factory=lambda: ["direct", "group_chat", "third_party"])
    routes_unknown: list[str] = Field(default_factory=lambda: ["private_only", "absent", "memo"])
    acts: list[Literal["decide", "propose"]] = Field(default_factory=lambda: ["decide", "propose"])
    tones: list[Literal["casual", "polite"]] = Field(default_factory=lambda: ["casual", "polite"])
    variants: list[str] = Field(default_factory=lambda: ["known_conflict", "known_compatible", "unknown_conflict"])

    min_turns: int = 2
    max_turns: int = 6
    # 既存データ（予備など）と同じ場面を作らないために、その scene_signature を除外する
    avoid_scenes_in: list[str] = Field(default_factory=list)

    model: ModelConfig = Field(default_factory=ModelConfig)  # method: llm のとき
    extra_instructions: str = ""  # llm への追加の指示

    # format: friction のとき
    friction_causes: list[str] = Field(default_factory=lambda: [
        "common_ground_gap", "private_context_unknown", "relevance_mismatch",
        "intent_misread", "emotional_neglect", "relationship_norm_gap"])
    friction_ratio: float = 0.7  # 摩擦ありを意図する会話の割合


@dataclass
class SceneSpec:
    scene_no: int
    split: str
    domain: str
    relationship: str
    route_known: str
    route_unknown: str
    act: str
    tone: str
    variants: list[str] = field(default_factory=list)
    friction_cause: str = ""
    friction_intended: bool = True


def load_gen_config(path: str | Path) -> GenConfig:
    with Path(path).open(encoding="utf-8") as f:
        return GenConfig.model_validate(yaml.safe_load(f))


def _balanced(values: list, n: int, rng: random.Random) -> list:
    """各値がほぼ同じ回数ずつ出るように並べる（1巡ごとにシャッフル）。"""
    out: list = []
    while len(out) < n:
        v = values[:]
        rng.shuffle(v)
        out += v
    return out[:n]


def plan_specs(cfg: GenConfig) -> list[SceneSpec]:
    rng = random.Random(cfg.seed)
    n = cfg.n_scenes
    cols = {k: _balanced(getattr(cfg, k), n, rng) for k in
            ("domains", "relationships", "routes_known", "routes_unknown", "acts", "tones")}
    causes = _balanced(cfg.friction_causes, n, rng)
    n_fric = round(n * cfg.friction_ratio)
    intended = _balanced([True] * n_fric + [False] * (n - n_fric), n, rng)
    return [
        SceneSpec(
            scene_no=i + 1, split=cfg.split,
            domain=cols["domains"][i], relationship=cols["relationships"][i],
            route_known=cols["routes_known"][i], route_unknown=cols["routes_unknown"][i],
            act=cols["acts"][i], tone=cols["tones"][i], variants=list(cfg.variants),
            friction_cause=causes[i], friction_intended=intended[i],
        )
        for i in range(n)
    ]
