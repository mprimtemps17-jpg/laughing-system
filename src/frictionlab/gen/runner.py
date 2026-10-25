"""生成の実行。データ（.jsonl）と、生成記録（.log.jsonl）・点検レポート（.report.md）を書き出す。"""

from __future__ import annotations

import json
import random
from collections import Counter
from datetime import datetime
from pathlib import Path

import yaml

from ..care.items import CareItem, load_items, save_items
from ..friction.data import Dialogue
from ..llm import PendingResponse, call_with_retry, check_result, make_backend
from .llm_gen import NAMES, care_prompt, friction_prompt
from .quality import check_care_variants, near_duplicates
from .spec import GenConfig, SceneSpec, plan_specs
from .templates import INTENDED, generate_scene

VARIANT_NO = {"known_conflict": 1, "known_compatible": 2, "unknown_conflict": 3, "known_updated": 4}
MAX_ATTEMPTS = 20


def _avoided_signatures(cfg: GenConfig) -> set[str]:
    sigs = set()
    for path in cfg.avoid_scenes_in:
        for it in load_items(path):
            if it.scene_signature:
                sigs.add(it.scene_signature)
    return sigs


def _care_items(cfg: GenConfig, spec: SceneSpec, variants: list[dict], signature: str) -> list[CareItem]:
    sid = f"{cfg.id_prefix}{spec.scene_no:03d}"
    items = []
    for v in variants:
        items.append(CareItem(
            id=f"{sid}-{VARIANT_NO.get(v['variant'], 9)}", scene_id=sid, variant=v["variant"], split=spec.split,
            domain=spec.domain, route=v["route"], scene_signature=signature,
            background=v["background"], turns=v["turns"], target=v["target"],
            intended_label=v["intended_label"], intended_reason=v["intended_reason"],
            version=f"gen:{cfg.name}", source=f"{cfg.method}生成（{datetime.now():%Y-%m-%d}）",
            notes=f"relationship={spec.relationship}, act={spec.act}, tone={spec.tone}",
        ))
    return items


def _from_llm_care(spec: SceneSpec, out: dict) -> tuple[str, list[dict]]:
    variants = []
    for name in spec.variants:
        v = out["variants"][name]
        route = spec.route_unknown if name.startswith("unknown") else spec.route_known
        variants.append({"variant": name, "route": route, "background": v["background"].strip(),
                         "turns": v["turns"], "target": v["target"].strip(),
                         "intended_label": INTENDED[name], "intended_reason": v["reason"]})
    return f"llm:{spec.domain}:{out['scene_summary']}", variants


def run_generation(cfg: GenConfig, config_path: str | None = None) -> Path:
    out_path = Path(cfg.output)
    if cfg.format == "friction" and cfg.method != "llm":
        raise ValueError("format: friction は method: llm でのみ生成できます")

    specs = plan_specs(cfg)
    used = _avoided_signatures(cfg)
    avoid_summaries: list[str] = []
    rng = random.Random(cfg.seed)
    log_path = out_path.with_suffix(".log.jsonl")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    backend = None
    if cfg.method == "llm":
        if cfg.model.backend == "manual" and not cfg.model.manual_dir:
            cfg.model.manual_dir = str(out_path.parent / f"{out_path.stem}_manual")
        backend = make_backend(cfg.model)

    accepted: list = []
    rejected, pending = [], 0
    with log_path.open("w", encoding="utf-8") as log:
        for spec in specs:
            rec = {"scene_no": spec.scene_no, "spec": spec.__dict__}
            if cfg.method == "template":
                for _ in range(MAX_ATTEMPTS):  # 既出の場面と重ならない組み合わせを探す
                    sig, variants = generate_scene(spec, rng)
                    if sig not in used:
                        issues = check_care_variants(variants, cfg.min_turns, cfg.max_turns)
                        break
                else:
                    issues = [f"{spec.domain} の語彙が足りず、既出と重ならない場面を作れない（templates.py に語彙を追加する）"]
            else:
                prompt_fn = care_prompt if cfg.format == "care" else friction_prompt
                system, user, schema = prompt_fn(spec, cfg, avoid_summaries)
                seed = f"gen-{cfg.name}-{spec.scene_no:03d}"
                try:
                    res = call_with_retry(lambda: backend.generate_json(system, user, schema, seed=seed))
                except PendingResponse:
                    pending += 1
                    continue
                rec.update(raw=res.text, model=res.model, usage=res.usage)
                err = check_result(res)
                if err:
                    rec["issues"] = [err]
                    rejected.append(rec)
                    log.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    continue
                out = json.loads(res.text)
                if cfg.format == "friction":
                    sig = f"llm-friction:{out['setting'][:30]}"
                    issues = [] if 4 <= len(out["turns"]) <= 12 else ["発言数が範囲外"]
                    variants = out
                else:
                    sig, variants = _from_llm_care(spec, out)
                    issues = check_care_variants(variants, cfg.min_turns, cfg.max_turns)
                avoid_summaries.append(sig.split(":", 2)[-1])

            rec.update(signature=sig, issues=issues)
            log.write(json.dumps(rec, ensure_ascii=False) + "\n")
            if issues:
                rec["variants"] = variants
                rejected.append(rec)
                continue
            used.add(sig)
            if cfg.format == "care":
                accepted += _care_items(cfg, spec, variants, sig)
            else:
                accepted.append(_friction_dialogue(cfg, spec, variants, rng))

    # 異なる場面どうしで似すぎていないか
    dups = []
    if cfg.format == "care":
        texts = {it.id: (it.scene_id, it.background + "".join(t.text for t in it.turns) + it.target) for it in accepted}
        dups = near_duplicates(texts)
        save_items(accepted, out_path)
    else:
        with out_path.open("w", encoding="utf-8") as f:
            for d in accepted:
                f.write(json.dumps(d.model_dump(exclude_none=True), ensure_ascii=False) + "\n")

    _write_report(cfg, out_path, specs, accepted, rejected, dups, pending, config_path)
    if pending:
        print(f"[manual] {pending} 場面が回答待ちです。{cfg.model.manual_dir}/ の *.prompt.md をチャット画面に貼り付け、"
              "回答を同名の *.response.txt に保存してから、同じコマンドをもう一度実行してください。")
    return out_path


def _friction_dialogue(cfg: GenConfig, spec: SceneSpec, out: dict, rng: random.Random) -> Dialogue:
    a, b = rng.sample(NAMES, 2)
    intended = {
        "friction": out["friction"], "severity": out["severity"], "friction_turns": out["friction_turns"],
        "causes": [spec.friction_cause] if out["friction"] else [], "annotator": f"generator:{cfg.name}",
        "perceived_by": {"A": out["perceived_by_A"], "B": out["perceived_by_B"]},
    }
    n = len(out["turns"])
    intended["friction_turns"] = [t for t in intended["friction_turns"] if 1 <= t <= n]
    return Dialogue.model_validate({
        "id": f"{cfg.id_prefix}{spec.scene_no:03d}", "setting": out["setting"], "speakers": {"A": a, "B": b},
        "private_info": {"A": out["private_info_A"], "B": out["private_info_B"]},
        "turns": [t for t in out["turns"] if t["speaker"] in ("A", "B")],
        "intended": intended, "source": f"llm生成:{cfg.name}", "notes": out["reason"],
    })


def _write_report(cfg, out_path, specs, accepted, rejected, dups, pending, config_path) -> None:
    lines = [
        f"# 生成レポート: {cfg.name}",
        "",
        f"- 方法: {cfg.method} / 形式: {cfg.format} / seed: {cfg.seed} / 設定: {config_path or '-'}",
        f"- 計画した場面: {len(specs)} / 採用: {len(accepted)} 件 / 不採用の場面: {len(rejected)} / 回答待ち: {pending}",
        f"- 出力: `{out_path}`（生成記録: `{out_path.with_suffix('.log.jsonl').name}`）",
        "",
        "> 作成意図のラベルは正解ではありません。実験に使う前に、人間が独立に判定してください。",
        "",
    ]
    if cfg.format == "care" and accepted:
        for key in ("split", "domain", "variant", "route", "intended_label"):
            c = Counter(getattr(it, key) for it in accepted)
            lines.append(f"- {key}: " + ", ".join(f"{k} {v}" for k, v in sorted(c.items())))
        rel = Counter(it.notes.split(",")[0].split("=")[1] for it in accepted)
        lines.append("- relationship: " + ", ".join(f"{k} {v}" for k, v in sorted(rel.items())))
    if rejected:
        lines += ["", "## 不採用（自動点検で問題あり）", ""]
        lines += [f"- 場面 {r['scene_no']}: {'; '.join(r.get('issues', []))}" for r in rejected]
    if dups:
        lines += ["", "## 似すぎている組（異なる場面どうし。どちらかを見直す）", ""]
        lines += [f"- {a} と {b}: 類似度 {s}" for a, b, s in dups]
    out_path.with_suffix(".report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:5]))
