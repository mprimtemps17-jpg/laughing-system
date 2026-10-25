"""生成した会話の自動点検。

ここで見つけられるのは形式上の問題と明らかな手掛かり語だけ。内容の妥当性（本当に「あり」と言えるか等）は
人間の判定で確かめる。
"""

from __future__ import annotations

# 答えに直結する露骨な手掛かり（研究設計 v0.2：「露骨な『配慮しない』という答えに直結する言葉は使わない」）
CUE_WORDS = ["配慮しない", "配慮せず", "気にしない", "気にせず", "無視して", "無視する", "わざと",
             "説明しないよ", "説明はしない", "知ってるけど", "知っているけど", "関係ない", "どうでもいい"]

# 未知条件の背景に、Aが知らないことの明示があるかの手掛かり
UNKNOWN_MARKERS = ["知らない", "伝えておらず", "伝えていない", "その場におらず", "その場にいな", "見ておらず",
                   "見ていない", "聞いたこともない", "Bだけ", "知ったこともない"]


def check_care_variants(variants: list[dict], min_turns: int, max_turns: int) -> list[str]:
    issues = []
    by_v = {v["variant"]: v for v in variants}
    for v in variants:
        name = v["variant"]
        turns = v.get("turns", [])
        n_utt = sum(t["speaker"] in ("A", "B") for t in turns)
        if not (min_turns <= n_utt <= max_turns):
            issues.append(f"{name}: 発言数 {n_utt} が範囲 {min_turns}〜{max_turns} の外")
        if any(not t.get("text", "").strip() for t in turns) or not v.get("target", "").strip():
            issues.append(f"{name}: 空の発言がある")
        if any(t["speaker"] not in ("A", "B", "narration") for t in turns):
            issues.append(f"{name}: 話者はA・B・narrationのみ")
        text = v.get("background", "") + "".join(t["text"] for t in turns) + v.get("target", "")
        hits = [w for w in CUE_WORDS if w in text]
        if hits:
            issues.append(f"{name}: 露骨な手掛かり語 {hits}")
        if v.get("target", "").startswith(("A「", "A:", "A：")):
            issues.append(f"{name}: 対象発言に話者名が含まれている")
    if "known_conflict" in by_v and "unknown_conflict" in by_v:
        if by_v["known_conflict"]["target"].strip() != by_v["unknown_conflict"]["target"].strip():
            issues.append("known_conflict と unknown_conflict の対象発言が同一でない")
        if not any(m in by_v["unknown_conflict"].get("background", "") for m in UNKNOWN_MARKERS):
            issues.append("unknown_conflict: Aが知らないことが背景に明示されていない可能性")
    if "known_conflict" in by_v and "known_compatible" in by_v:
        a, b = by_v["known_conflict"], by_v["known_compatible"]
        if a["background"] != b["background"] or a["turns"] != b["turns"]:
            issues.append("known_conflict と known_compatible で背景・会話が異なる（対象発言だけを変えるべき）")
    return issues


def ngrams(s: str, n: int = 3) -> set[str]:
    s = "".join(s.split())
    return {s[i:i + n] for i in range(max(1, len(s) - n + 1))}


def similarity(a: str, b: str) -> float:
    x, y = ngrams(a), ngrams(b)
    return len(x & y) / len(x | y) if x | y else 0.0


def near_duplicates(texts: dict[str, tuple[str, str]], threshold: float = 0.9) -> list[tuple[str, str, float]]:
    """{id: (scene_id, text)} から、異なる場面どうしで似すぎている組を返す。"""
    ids = list(texts)
    out = []
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            if texts[a][0] == texts[b][0]:
                continue
            s = similarity(texts[a][1], texts[b][1])
            if s >= threshold:
                out.append((a, b, round(s, 3)))
    return out
