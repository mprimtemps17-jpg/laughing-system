"""条件に応じて判定プロンプトを組み立てる。

プロンプトの文面を変えると結果が変わるので、ここを変更したら
新しい実行（run）として記録し、古い結果と混ぜないこと。
"""

from __future__ import annotations

import hashlib

from .config import Cause, Condition
from .data import Dialogue

PROMPT_VERSION = "v1"

SYSTEM_PROMPT = """\
あなたは対人コミュニケーションを分析する研究補助者です。
二者間の会話ログを読み、会話の中に「摩擦」が生じているかを判定します。

ここでの「摩擦」とは、次のいずれかを指します。
- 発言が相手を傷つけたり、不快・気まずくさせたりしている（配慮不足・無神経な発言）
- 話し手と聞き手の間で、前提・意図・重要だと思っていることがずれている（すれ違い）

判定は、ログと与えられた情報だけに基づいて行ってください。書かれていない事情を想像で補いすぎないでください。"""


def _swap(s: str) -> str:
    return {"A": "B", "B": "A"}.get(s, s)


def render_dialogue(d: Dialogue, swapped: bool = False) -> str:
    """ターン番号付きで会話を整形する。swapped=True ならA/Bのラベルを入れ替えて表示する。"""
    lines = []
    for i, t in enumerate(d.turns, 1):
        label = _swap(t.speaker) if swapped else t.speaker
        lines.append(f"[{i}] {label}（{d.speakers[t.speaker]}）: {t.text}")
    return "\n".join(lines)


def build_prompt(
    d: Dialogue, cond: Condition, taxonomy: list[Cause], swapped: bool = False
) -> tuple[str, str]:
    """(system, user) のプロンプトを返す。

    viewpoint / private_info は元データの話者（A/B）を指す。
    swapped=True のときは表示上のラベルだけを入れ替え、同じ人物を指すように変換する。
    """
    shown = (lambda s: _swap(s)) if swapped else (lambda s: s)
    name = d.speakers
    parts: list[str] = []

    # 視点の指定
    if cond.viewpoint == "observer":
        parts.append("あなたはこの会話の外にいる第三者（観察者）として判定してください。")
    else:
        v = cond.viewpoint
        parts.append(
            f"あなたは話者{shown(v)}（{name[v]}）本人の立場に立って判定してください。"
            f"{name[v]}がこの会話の中で、どこかで引っかかりや不快感、すれ違いを感じたかを考えてください。"
        )

    # 共有状況
    if cond.setting == "include" and d.setting:
        parts.append(f"## 会話の状況（両者が共有している情報）\n{d.setting}")

    # 片方だけが知る情報
    targets = {"none": [], "A": ["A"], "B": ["B"], "both": ["A", "B"]}[cond.private_info]
    for s in sorted(targets, key=shown):
        items = d.private_info.get(s, [])
        if not items:
            continue
        other = "B" if s == "A" else "A"
        bullet = "\n".join(f"- {x}" for x in items)
        parts.append(
            f"## {shown(s)}（{name[s]}）だけが知っている情報"
            f"（{shown(other)}（{name[other]}）はこのことを知りません）\n{bullet}"
        )

    parts.append(f"## 会話ログ\n{render_dialogue(d, swapped)}")

    cause_lines = "\n".join(f"- {c.id}: {c.label} — {c.description}" for c in taxonomy)
    parts.append(
        "## 回答方法\n"
        "以下の項目をJSONで答えてください。\n"
        "- friction: 摩擦があるか（true/false）\n"
        "- severity: 摩擦の強さ 0=なし, 1=軽い違和感, 2=明らかな気まずさ・不快, 3=関係を損なうほど深刻\n"
        "- friction_turns: 摩擦が生じたターン番号のリスト（なければ空）\n"
        "- caused_by: 摩擦のきっかけを作った話者（A / B / both / none）\n"
        "- causes: 摩擦の要因（下の分類から該当するIDをすべて。なければ空）\n"
        "- rationale: 判断の根拠（日本語で2〜4文）\n\n"
        f"要因の分類:\n{cause_lines}"
    )
    return SYSTEM_PROMPT, "\n\n".join(parts)


def output_schema(taxonomy: list[Cause]) -> dict:
    """構造化出力のJSONスキーマ。"""
    return {
        "type": "object",
        "properties": {
            "friction": {"type": "boolean"},
            "severity": {"type": "integer", "enum": [0, 1, 2, 3]},
            "friction_turns": {"type": "array", "items": {"type": "integer"}},
            "caused_by": {"type": "string", "enum": ["A", "B", "both", "none"]},
            "causes": {"type": "array", "items": {"type": "string", "enum": [c.id for c in taxonomy]}},
            "rationale": {"type": "string"},
        },
        "required": ["friction", "severity", "friction_turns", "caused_by", "causes", "rationale"],
        "additionalProperties": False,
    }


def prompt_hash(system: str, user: str) -> str:
    return hashlib.sha256((system + "\x00" + user).encode("utf-8")).hexdigest()[:16]
