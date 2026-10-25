import random
from pathlib import Path

import yaml

from frictionlab.care.items import check_splits, load_items
from frictionlab.gen.quality import check_care_variants
from frictionlab.gen.runner import run_generation
from frictionlab.gen.spec import GenConfig, SceneSpec, load_gen_config, plan_specs
from frictionlab.gen.templates import DOMAINS, generate_scene

ROOT = Path(__file__).resolve().parents[1]


def test_plan_is_balanced():
    cfg = GenConfig(name="t", output="x.jsonl", n_scenes=12, domains=["time", "budget", "dietary"])
    specs = plan_specs(cfg)
    counts = {d: sum(s.domain == d for s in specs) for d in cfg.domains}
    assert set(counts.values()) == {4}


def test_every_template_combination_passes_checks():
    rng = random.Random(0)
    variants = ["known_conflict", "known_compatible", "unknown_conflict", "known_updated"]
    for domain in DOMAINS:
        for rk in ("direct", "group_chat", "third_party"):
            for ru in ("private_only", "absent", "memo"):
                for act in ("decide", "propose"):
                    spec = SceneSpec(1, "dev", domain, "seminar", rk, ru, act, "polite", variants)
                    _, vs = generate_scene(spec, rng)
                    assert check_care_variants(vs, 2, 6) == [], (domain, rk, ru, act)
                    by = {v["variant"]: v for v in vs}
                    assert by["known_conflict"]["target"] == by["unknown_conflict"]["target"]


def test_generation_writes_valid_items(tmp_path):
    raw = yaml.safe_load((ROOT / "configs/gen/time_eval_template.yaml").read_text(encoding="utf-8"))
    raw["output"] = str(tmp_path / "g.jsonl")
    cfg = GenConfig.model_validate(raw)
    out = run_generation(cfg)
    items = load_items(out)
    assert len(items) == 24
    assert check_splits(items) == []
    assert {it.intended_label for it in items} == {"あり", "なし", "判定対象外"}
    assert len({it.scene_signature for it in items}) == 8
    # 同じ設定なら同じものが作られる（再現性）
    again = load_items(run_generation(cfg))
    assert [i.model_dump() for i in items] == [i.model_dump() for i in again]


def test_shipped_configs_load():
    for p in (ROOT / "configs/gen").glob("*.yaml"):
        load_gen_config(p)
