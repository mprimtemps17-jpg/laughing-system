"""判定・知識整理のプロンプト。

3条件とも、最終判定には同じ文脈・対象発言・判定基準・出力形式を渡す。
B・C の第1段階には対象発言と正解ラベルを見せない。
文面を変えたら PROMPT_VERSION を上げ、古い結果と混ぜないこと。
"""

from __future__ import annotations

import json

from .items import LABELS, CareItem, render_context

PROMPT_VERSION = "care-v0.2.0"

SYSTEM_JUDGE = """\
あなたは日本語会話の指定発言を判定する第三者の評価者です。
判定対象は、Aの「対象発言」1つだけです。本文にない事情や感情を創作しないでください。"""

SYSTEM_ORGANIZE = """\
あなたは日本語会話の内容を整理する補助者です。
本文に明記された事実だけを短く書き出してください。人物の内面の推測や、発言の適切さの判断はしないでください。"""

# B：人物ごとの知識整理（SimToMに着想を得た改変。原手法の再現ではない）
KNOWLEDGE_FIELDS = {
    "constraint": "Bの制約の内容（時刻・条件など）",
    "a_knows": "Aが知っている内容と、それが分かる本文の引用",
    "b_only": "Bだけが知っている内容と、それが分かる本文の引用",
    "shared": "伝達や応答によって、A・Bの間で共有されたと確認できる内容",
    "unknown": "本文からは分からないこと（情報不足）",
}

# C：人物別にしない一般的な整理（対照条件）。項目数と長さの上限をBにそろえる
GENERAL_FIELDS = {
    "overview": "場面の概要",
    "sequence": "出来事の順序（時系列）",
    "conditions": "本文に出てくる具体的な条件や数値",
    "quotes": "関連する本文の引用",
    "unknown": "本文からは分からないこと（情報不足）",
}

FIELD_MAX_CHARS = 80


def judge_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "label": {"type": "string", "enum": list(LABELS)},
            "evidence": {"type": "array", "items": {"type": "string"}},
            "reason": {"type": "string"},
        },
        "required": ["label", "evidence", "reason"],
        "additionalProperties": False,
    }


def organize_schema(fields: dict[str, str]) -> dict:
    return {
        "type": "object",
        "properties": {k: {"type": "string"} for k in fields},
        "required": list(fields),
        "additionalProperties": False,
    }


def organize_prompt(item: CareItem, kind: str) -> tuple[str, str, dict]:
    """第1段階（B: knowledge / C: general）のプロンプト。対象発言は含めない。"""
    fields = KNOWLEDGE_FIELDS if kind == "knowledge" else GENERAL_FIELDS
    how = (
        "AとBのそれぞれについて、誰がどの情報を知っているかを分けて整理してください。"
        if kind == "knowledge"
        else "人物ごとに分けず、場面全体を時系列で短く整理してください。"
    )
    items = "\n".join(f"- {k}: {v}" for k, v in fields.items())
    user = (
        f"次の文脈を読み、{how}\n"
        f"各項目は{FIELD_MAX_CHARS}字以内。分からない場合は「不明」と書いてください。\n\n"
        f"{render_context(item)}\n\n"
        f"## 出力する項目（JSON）\n{items}"
    )
    return SYSTEM_ORGANIZE, user, organize_schema(fields)


def judge_prompt(item: CareItem, criteria: str, organized: dict | None = None, kind: str | None = None) -> tuple[str, str, dict]:
    """最終判定のプロンプト。organized があれば第1段階の整理結果を添える。"""
    parts = [
        f"## 判定基準\n{criteria.strip()}",
        f"## 文脈\n{render_context(item)}",
        f"## 対象発言（A）\n{item.target}",
    ]
    if organized is not None:
        title = "人物ごとの知識整理（前段で作成）" if kind == "knowledge" else "場面の整理（前段で作成）"
        parts.append(
            f"## {title}\n```json\n{json.dumps(organized, ensure_ascii=False, indent=1)}\n```\n"
            "元の文脈とこの整理の両方に基づいて判定してください。"
        )
    parts.append(
        "## 回答方法\n"
        "次の項目をJSONで答えてください。\n"
        f"- label: {' / '.join(LABELS)} のどれか1つ\n"
        "- evidence: 判定の根拠となる本文の短い引用（Aの情報アクセスが分かる箇所、制約と発言が分かる箇所）。"
        "引用できる根拠がなければ空配列\n"
        "- reason: 本文に基づく短い理由（100字以内）"
    )
    return SYSTEM_JUDGE, "\n\n".join(parts), judge_schema()
