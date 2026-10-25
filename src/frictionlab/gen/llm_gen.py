"""LLMによる会話生成のプロンプトとスキーマ。"""

from __future__ import annotations

from .spec import DOMAIN_DESC, ROUTE_KNOWN_DESC, ROUTE_UNKNOWN_DESC, VARIANT_DESC, GenConfig, SceneSpec
from .templates import RELATIONSHIPS, tones

SYSTEM_CARE = """\
あなたは、日本語の会話研究のための実験素材を作る作成者です。
大学生や若い社会人の、自然で短い日常会話を作ります。
作る素材は、第三者が「Aの対象発言が、Aの知っているBの制約を反映しているか」を判定する課題に使われます。"""

TURN_SCHEMA = {
    "type": "object",
    "properties": {
        "speaker": {"type": "string", "enum": ["A", "B", "narration"]},
        "text": {"type": "string"},
    },
    "required": ["speaker", "text"],
    "additionalProperties": False,
}


def care_schema(variants: list[str]) -> dict:
    variant_obj = {
        "type": "object",
        "properties": {
            "background": {"type": "string"},
            "turns": {"type": "array", "items": TURN_SCHEMA},
            "target": {"type": "string"},
            "reason": {"type": "string"},
        },
        "required": ["background", "turns", "target", "reason"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "scene_summary": {"type": "string"},
            "constraint": {"type": "string"},
            "variants": {
                "type": "object",
                "properties": {v: variant_obj for v in variants},
                "required": list(variants),
                "additionalProperties": False,
            },
        },
        "required": ["scene_summary", "constraint", "variants"],
        "additionalProperties": False,
    }


def care_prompt(spec: SceneSpec, cfg: GenConfig, avoid: list[str]) -> tuple[str, str, dict]:
    ta, tb = tones(spec)
    rel = RELATIONSHIPS.get(spec.relationship, (spec.relationship, None, None))[0]
    act = {"decide": "決定する（「〜で決定にするね」など）", "propose": "断定的に提案する（「〜にしよう」など）"}[spec.act]
    tone = {"casual": "くだけた話し言葉", "polite": "丁寧語（です・ます）"}
    variants = "\n".join(f"- {v}: {VARIANT_DESC[v]}" for v in spec.variants)
    avoid_txt = "\n".join(f"- {a}" for a in avoid[-30:]) or "（なし）"
    user = f"""次の仕様で、1つの基本場面と、その変種を作ってください。

## 仕様
- 場面の種類: {DOMAIN_DESC.get(spec.domain, spec.domain)}
- 2人の関係: {rel}
- Aの口調: {tone[ta]} / Bの口調: {tone[tb]}
- Aが制約を知る経路（known_* の変種）: {ROUTE_KNOWN_DESC[spec.route_known]}
- Aが制約を知らない経路（unknown_conflict）: {ROUTE_UNKNOWN_DESC[spec.route_unknown]}
- 衝突する対象発言の形: {act}

## 作る変種
{variants}

## 守ること
- 登場人物はAとBの2人。第三者が必要なら背景の中でCとして書く。
- background は場面の説明（地の文）。turns は対象発言の直前までの会話で、A・Bの発言は合計{cfg.min_turns}〜{cfg.max_turns}個。
- target はAの1発言（話者名やかぎかっこは付けない）。turns の直後に来る発言とする。
- target の後のBの反応（怒る・断るなど）は書かない。反応から答えが分かってしまうため。
- 制約は具体的に書く（時刻・金額・品目・できないことなど）。曖昧な表現にしない。
- 「配慮しない」「無視して」「わざと」「説明しないよ」のような、答えに直結する露骨な言葉を使わない。
- 口調の丁寧さと、制約を反映しているかどうかを結びつけない（丁寧でも衝突し得るし、くだけていても適合し得る）。
- reason には、その変種で意図したことを1文で書く（評価者・モデルには見せない）。
- scene_summary には場面を20字程度で、constraint には制約を1文で書く。

## これまでに作った場面（これらと似た場面は避ける）
{avoid_txt}
"""
    if cfg.extra_instructions:
        user += f"\n## 追加の指示\n{cfg.extra_instructions}\n"
    return SYSTEM_CARE, user, care_schema(spec.variants)


# ---------------------------------------------------------------- 探索実験（friction）の形式
SYSTEM_FRICTION = """\
あなたは、日本語の会話研究のための実験素材を作る作成者です。
2人の自然な日常会話を作り、それぞれが相手の知らない事情（私的な情報）を持つように設定します。"""

CAUSE_DESC = {
    "common_ground_gap": "共有知識（共通基盤）のずれ：相手が知らないことを知っている前提で話す",
    "private_context_unknown": "相手の個人的事情を知らない・考慮しない",
    "relevance_mismatch": "何を重要とみなすかのずれ",
    "intent_misread": "冗談・遠回しな表現などの発話意図の読み違い",
    "emotional_neglect": "相手の感情への配慮不足",
    "relationship_norm_gap": "関係性・役割について、許される言い方の感覚のずれ",
}

NAMES = ["ユウキ", "ハルカ", "ソラ", "アオイ", "ヒカル", "マコト", "リン", "カオル", "ミズキ", "アキラ", "ツバサ", "ナギサ"]


def friction_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "setting": {"type": "string"},
            "private_info_A": {"type": "array", "items": {"type": "string"}},
            "private_info_B": {"type": "array", "items": {"type": "string"}},
            "turns": {"type": "array", "items": TURN_SCHEMA},
            "friction": {"type": "boolean"},
            "severity": {"type": "integer", "enum": [0, 1, 2, 3]},
            "friction_turns": {"type": "array", "items": {"type": "integer"}},
            "perceived_by_A": {"type": "boolean"},
            "perceived_by_B": {"type": "boolean"},
            "reason": {"type": "string"},
        },
        "required": ["setting", "private_info_A", "private_info_B", "turns", "friction", "severity",
                     "friction_turns", "perceived_by_A", "perceived_by_B", "reason"],
        "additionalProperties": False,
    }


def friction_prompt(spec: SceneSpec, cfg: GenConfig, avoid: list[str]) -> tuple[str, str, dict]:
    rel = RELATIONSHIPS.get(spec.relationship, (spec.relationship, None, None))[0]
    if spec.friction_intended:
        goal = (f"会話の途中で、次の要因による摩擦（すれ違い・配慮不足）が自然に起きるようにする: "
                f"{CAUSE_DESC.get(spec.friction_cause, spec.friction_cause)}。"
                "摩擦は片方の私的な情報と関係していてもよい。")
    else:
        goal = "私的な情報はあるが、会話自体には摩擦が起きない（互いに配慮できている、または問題にならない）ようにする。"
    avoid_txt = "\n".join(f"- {a}" for a in avoid[-30:]) or "（なし）"
    user = f"""次の仕様で、2人の日常会話を1つ作ってください。

## 仕様
- 2人の関係: {rel}
- 口調: {"くだけた話し言葉" if spec.tone == "casual" else "丁寧語を含む話し言葉"}
- ねらい: {goal}

## 守ること
- 話者はAとBのみ。turns は合計{max(4, cfg.min_turns)}〜{max(8, cfg.max_turns)}発言。
- private_info_A / private_info_B には、それぞれ本人だけが知っていて相手は知らない事情を1〜2個書く。
- 摩擦をセリフで説明しすぎない（「傷ついた」と言わせるなど）。読み手が気づける程度にする。
- friction / severity（0〜3）/ friction_turns（1始まりのターン番号）/ perceived_by_A / perceived_by_B には、
  作成者として意図した答えを書く（これは正解ではなく、人間の判定で確かめる）。
- reason には意図を1〜2文で書く。

## これまでに作った会話（これらと似た場面は避ける）
{avoid_txt}
"""
    if cfg.extra_instructions:
        user += f"\n## 追加の指示\n{cfg.extra_instructions}\n"
    return SYSTEM_FRICTION, user, friction_schema()
