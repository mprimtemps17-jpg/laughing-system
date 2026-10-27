"""回答サイト（HTML）を作る。

評価票（Excel）と同じく、作成意図ラベル・元のID・場面ID・変種はページに含めない。
問題は中立的なコード（sheet_id）で識別し、同じ場面の別パターンが続かないように
場面をハッシュ化したグループ記号だけを持たせる。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .humaneval import sheet_id
from .items import CareItem

TEMPLATE = Path(__file__).with_name("survey_template.html")


def _group(scene_id: str) -> str:
    return hashlib.sha1(f"frictionlab-scene:{scene_id}".encode()).hexdigest()[:6]


def survey_items(sets: dict[str, list[CareItem]]) -> list[dict]:
    out = []
    for set_key, items in sets.items():
        for it in items:
            out.append({
                "code": sheet_id(it.id), "set": set_key, "group": _group(it.scene_id),
                "background": it.background,
                "turns": [{"s": "N" if t.speaker == "narration" else t.speaker, "t": t.text} for t in it.turns],
                "target": it.target,
            })
    return out


def build_survey(sets: dict[str, list[CareItem]], criteria: str, out_path: str | Path) -> Path:
    def js(v) -> str:  # </script> でスクリプトが途切れないようにする
        return json.dumps(v, ensure_ascii=False).replace("</", "<\\/")

    html = TEMPLATE.read_text(encoding="utf-8")
    html = html.replace("__ITEMS__", js(survey_items(sets))).replace("__CRITERIA__", js(criteria.strip()))
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    return out_path
