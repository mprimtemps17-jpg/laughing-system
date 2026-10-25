import json
import shutil
from pathlib import Path

import pytest
import yaml

from frictionlab.friction.analysis import analyze
from frictionlab.friction.config import Condition, config_warnings, load_experiment, load_taxonomy
from frictionlab.friction.data import Dialogue, load_dialogues
from frictionlab.friction.prompts import build_prompt
from frictionlab.friction.runner import parse_judgment, run_experiment

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/friction_examples/sample_dialogues.jsonl"
TAX = ROOT / "configs/friction/taxonomy.yaml"


def test_sample_data_loads():
    ds = load_dialogues(DATA)
    assert len(ds) >= 8
    assert all(d.human_label is not None for d in ds)


def test_invalid_friction_turn_rejected():
    with pytest.raises(ValueError):
        Dialogue.model_validate({
            "id": "x", "speakers": {"A": "a", "B": "b"},
            "turns": [{"speaker": "A", "text": "1"}, {"speaker": "B", "text": "2"}],
            "human_label": {"friction": True, "friction_turns": [5]},
        })


def test_private_info_only_in_matching_condition():
    d = load_dialogues(DATA)[0]
    tax = load_taxonomy(TAX)
    secret_b = d.private_info["B"][0]
    _, base = build_prompt(d, Condition(name="b"), tax)
    _, pov = build_prompt(d, Condition(name="p", viewpoint="B", private_info="B"), tax)
    _, pov_a = build_prompt(d, Condition(name="pa", viewpoint="A", private_info="A"), tax)
    assert secret_b not in base
    assert secret_b in pov
    assert secret_b not in pov_a


def test_swap_relabels_same_person():
    d = load_dialogues(DATA)[0]
    tax = load_taxonomy(TAX)
    _, user = build_prompt(d, Condition(name="p", viewpoint="B", private_info="B"), tax, swapped=True)
    # 元のB（ハルカ）は入れ替え後「A」と表示され、視点人物もハルカのまま
    assert "話者A（ハルカ）本人の立場" in user
    assert "A（ハルカ）だけが知っている情報" in user
    assert parse_judgment('{"caused_by": "A"}', swapped=True)["caused_by"] == "B"
    assert parse_judgment('{"caused_by": "both"}', swapped=True)["caused_by"] == "both"


def test_config_warns_on_multi_factor_change():
    cfg = load_experiment(ROOT / "configs/friction/experiment.yaml")
    assert config_warnings(cfg) == []
    cfg.conditions.append(Condition(name="bad", viewpoint="A", private_info="B"))
    warns = config_warnings(cfg)
    assert any("2 個の要因" in w for w in warns)
    assert any("知り得ない" in w for w in warns)


def test_end_to_end_mock(tmp_path, monkeypatch):
    monkeypatch.chdir(ROOT)
    cfg_path = tmp_path / "exp.yaml"
    raw = yaml.safe_load((ROOT / "configs/friction/experiment.yaml").read_text(encoding="utf-8"))
    raw["repeats"] = 1
    cfg_path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    cfg = load_experiment(cfg_path)

    out = run_experiment(cfg, str(cfg_path), out_root=str(tmp_path / "results"))
    lines = (out / "judgments.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 8 * len(cfg.conditions) * 2
    assert all(json.loads(x)["error"] is None for x in lines)

    # 再開しても重複実行しない
    run_experiment(cfg, str(cfg_path), resume=str(out))
    assert len((out / "judgments.jsonl").read_text(encoding="utf-8").splitlines()) == len(lines)

    report = analyze(out)
    text = report.read_text(encoding="utf-8")
    assert "mockバックエンド" in text
    assert (out / "analysis/summary.png").exists()
    shutil.rmtree(out)
