"""コマンドライン入口。

主実験（研究設計 v0.2：対象発言の配慮不足判定）
  python -m frictionlab care validate   configs/care/pilot.yaml
  python -m frictionlab care show-prompt configs/care/pilot.yaml --item P1-1 --condition B_knowledge
  python -m frictionlab care run        configs/care/pilot.yaml [--resume results/<run>]
  python -m frictionlab care analyze    results/<run> [--use-intended]

人間による独立判定
  python -m frictionlab human export    data/care/v0.2_pilot.jsonl --out human_eval/sheet_自分.csv --seed 1
  python -m frictionlab human import    data/care/v0.2_pilot.jsonl human_eval/sheet_自分.csv --annotator 自分
  python -m frictionlab human agreement data/care/v0.2_pilot.jsonl [--write-gold out.jsonl]

会話の生成
  python -m frictionlab gen plan configs/gen/time_template.yaml
  python -m frictionlab gen run  configs/gen/time_template.yaml
  python -m frictionlab gen show data/generated/time_template.jsonl [--scene G001]

探索実験（会話全体の摩擦・視点条件）
  python -m frictionlab friction validate|show-prompt|run|analyze ...
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path


# ---------------------------------------------------------------- care
def care_validate(args) -> int:
    from .care.config import CONDITIONS, load_care_config
    from .care.items import check_splits, load_items
    from .care.runner import select_items

    cfg = load_care_config(args.config)
    all_items = load_items(cfg.data)
    items = select_items(cfg)
    Path(cfg.criteria).read_text(encoding="utf-8")
    print(f"設定OK: {cfg.name} / 判定基準: {cfg.criteria}")
    print(f"データOK: {len(all_items)} 件（使用 {len(items)} 件）")
    for key in ("split", "variant", "domain"):
        c = Counter(getattr(it, key) for it in items)
        print(f"  {key}: " + ", ".join(f"{k} {v}" for k, v in sorted(c.items())))
    print(f"  正解ラベル(gold)あり: {sum(it.gold_label is not None for it in items)} 件 / "
          f"人間の判定あり: {sum(bool(it.human_labels) for it in items)} 件")
    for w in check_splits(all_items):
        print(f"[注意] {w}")
    n_calls = sum(CONDITIONS[c]["calls"] for c in cfg.conditions) * len(items) * cfg.repeats
    print(f"条件: {', '.join(CONDITIONS[c]['label'] for c in cfg.conditions)}")
    print(f"実行すると、最終判定 {len(items) * len(cfg.conditions) * cfg.repeats} 件 / "
          f"モデル呼び出し {n_calls} 回（backend={cfg.model.backend}, model={cfg.model.name}）")
    return 0


def care_show_prompt(args) -> int:
    from .care.config import CONDITIONS, load_care_config
    from .care.items import load_items
    from .care.prompts import judge_prompt, organize_prompt

    cfg = load_care_config(args.config)
    it = next((x for x in load_items(cfg.data) if x.id == args.item), None)
    if it is None:
        print(f"例 '{args.item}' が見つかりません", file=sys.stderr)
        return 1
    criteria = Path(cfg.criteria).read_text(encoding="utf-8")
    kind = CONDITIONS[args.condition]["organize"]
    if kind:
        s, u, _ = organize_prompt(it, kind)
        print(f"=== 第1段階 system ===\n{s}\n\n=== 第1段階 user ===\n{u}\n")
        organized = {k: "（第1段階の出力がここに入る）" for k in _["properties"]}
    else:
        organized = None
    s, u, _ = judge_prompt(it, criteria, organized, kind)
    print(f"=== 判定 system ===\n{s}\n\n=== 判定 user ===\n{u}")
    return 0


def care_run(args) -> int:
    from .care.config import load_care_config
    from .care.runner import run_care

    out = run_care(load_care_config(args.config), args.config, out_root=args.out, resume=args.resume)
    print(f"次に: python -m frictionlab care analyze {out}")
    return 0


def care_analyze(args) -> int:
    from .care.analysis import analyze_care

    print(f"レポート: {analyze_care(args.run_dir, use_intended=args.use_intended)}")
    return 0


# ---------------------------------------------------------------- human
def human_export(args) -> int:
    from .care.humaneval import export_sheet
    from .care.items import load_items

    items = load_items(args.data)
    if args.split:
        items = [it for it in items if it.split == args.split]
    if args.out.endswith(".xlsx"):
        from .care.workbook import export_workbook

        criteria = Path(args.criteria).read_text(encoding="utf-8")
        out = export_workbook(items, args.out, criteria, seed=args.seed)
        print(f"評価票（Excel）: {out}（{len(items)} 件、判定基準シート付き）")
    else:
        out = export_sheet(items, args.out, seed=args.seed)
        print(f"評価票: {out}（{len(items)} 件）")
        print("評価者には評価票と判定基準（configs/care/criteria_*.md）だけを渡してください。")
    print(f"提示順の記録（評価者には渡さない）: {out.with_suffix('.order.txt')}")
    return 0


def human_import(args) -> int:
    from .care.humaneval import import_sheet
    from .care.items import load_items, save_items

    items, problems = import_sheet(load_items(args.data), args.sheet, args.annotator)
    for p in problems:
        print(f"[注意] {p}")
    out = args.out or args.data
    save_items(items, out)
    print(f"{args.annotator} の判定を取り込みました → {out}")
    return 0


def human_agreement(args) -> int:
    from .care.humaneval import agreement, write_gold
    from .care.items import load_items

    items = load_items(args.data)
    text, table = agreement(items)
    print(text)
    if args.table:
        table.to_csv(args.table, index=False, encoding="utf-8-sig")
        print(f"例ごとの一覧: {args.table}")
    if args.write_gold:
        n = write_gold(items, table, args.write_gold)
        print(f"全員一致の {n} 件に gold_label を設定 → {args.write_gold}")
    return 0


# ---------------------------------------------------------------- gen
def gen_plan(args) -> int:
    from .gen.spec import load_gen_config, plan_specs

    cfg = load_gen_config(args.config)
    specs = plan_specs(cfg)
    print(f"{cfg.name}: {len(specs)} 場面 × 変種 {len(cfg.variants)} = 最大 {len(specs) * len(cfg.variants)} 件"
          f"（方法: {cfg.method}, 形式: {cfg.format}, split: {cfg.split}）")
    for s in specs:
        print(f"  {cfg.id_prefix}{s.scene_no:03d} {s.domain:<16} {s.relationship:<13} "
              f"既知:{s.route_known:<12} 未知:{s.route_unknown:<13} {s.act:<8} {s.tone}")
    if cfg.method == "llm":
        print(f"LLM呼び出し: {len(specs)} 回（backend={cfg.model.backend}）")
    return 0


def gen_run(args) -> int:
    from .gen.runner import run_generation
    from .gen.spec import load_gen_config

    run_generation(load_gen_config(args.config), args.config)
    return 0


def gen_show(args) -> int:
    from .care.items import load_items, render_context

    for it in load_items(args.data):
        if args.scene and it.scene_id != args.scene:
            continue
        print(f"--- {it.id}  [{it.variant} / {it.route} / 作成意図: {it.intended_label}]")
        print(render_context(it))
        print(f"【対象発言（A）】{it.target}\n")
    return 0


# ---------------------------------------------------------------- friction（探索実験）
def friction_validate(args) -> int:
    from .friction.config import config_warnings, load_experiment, load_taxonomy
    from .friction.data import load_dialogues

    cfg = load_experiment(args.config)
    ds = load_dialogues(cfg.data)
    tax = load_taxonomy(cfg.taxonomy)
    print(f"設定OK: {cfg.name} / 条件 {len(cfg.conditions)} 個 / 要因分類 {len(tax)} 個")
    print(f"データOK: 会話 {len(ds)} 件（人間ラベル付き {sum(d.human_label is not None for d in ds)} 件）")
    for c in cfg.conditions:
        diff = cfg.diff_from_reference(c)
        d = "基準" if c.name == cfg.baseline else (
            f"vs {cfg.reference_of(c)}: " + ", ".join(f"{k} {a}→{b}" for k, (a, b) in diff.items()))
        print(f"  - {c.name:<24} [{d}] {c.description}")
    for w in config_warnings(cfg):
        print(f"[注意] {w}")
    n = (min(len(ds), cfg.limit) if cfg.limit else len(ds)) * len(cfg.conditions) * cfg.repeats * (
        2 if cfg.swap_speakers else 1)
    print(f"実行すると {n} 回LLMを呼び出します（backend={cfg.model.backend}, model={cfg.model.name}）")
    return 0


def friction_show_prompt(args) -> int:
    from .friction.config import load_experiment, load_taxonomy
    from .friction.data import load_dialogues
    from .friction.prompts import build_prompt

    cfg = load_experiment(args.config)
    d = next((x for x in load_dialogues(cfg.data) if x.id == args.dialogue), None)
    if d is None:
        print(f"会話 '{args.dialogue}' が見つかりません", file=sys.stderr)
        return 1
    system, user = build_prompt(d, cfg.condition(args.condition), load_taxonomy(cfg.taxonomy), args.swap)
    print("=== system ===\n" + system + "\n\n=== user ===\n" + user)
    return 0


def friction_run(args) -> int:
    from .friction.config import load_experiment
    from .friction.runner import run_experiment

    out = run_experiment(load_experiment(args.config), args.config, out_root=args.out, resume=args.resume)
    print(f"次に: python -m frictionlab friction analyze {out}")
    return 0


def friction_analyze(args) -> int:
    from .friction.analysis import analyze

    print(f"レポート: {analyze(args.run_dir)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="frictionlab", description="会話の配慮不足・摩擦の判定実験")
    top = p.add_subparsers(dest="group", required=True)

    care = top.add_parser("care", help="主実験（v0.2：対象発言の配慮不足判定）").add_subparsers(dest="cmd", required=True)
    s = care.add_parser("validate", help="設定とデータを検査し、呼び出し回数を表示")
    s.add_argument("config")
    s.set_defaults(func=care_validate)
    s = care.add_parser("show-prompt", help="実際に送るプロンプトを表示")
    s.add_argument("config")
    s.add_argument("--item", required=True)
    s.add_argument("--condition", required=True, choices=["A_direct", "B_knowledge", "C_general"])
    s.set_defaults(func=care_show_prompt)
    s = care.add_parser("run", help="実行")
    s.add_argument("config")
    s.add_argument("--out", default="results")
    s.add_argument("--resume")
    s.set_defaults(func=care_run)
    s = care.add_parser("analyze", help="集計してレポートを作る")
    s.add_argument("run_dir")
    s.add_argument("--use-intended", action="store_true", help="正解ラベルがない例を作成意図のラベルで仮に集計")
    s.set_defaults(func=care_analyze)

    human = top.add_parser("human", help="人間による独立判定").add_subparsers(dest="cmd", required=True)
    s = human.add_parser("export", help="評価票（CSV）を作る")
    s.add_argument("data")
    s.add_argument("--out", required=True)
    s.add_argument("--seed", type=int, default=0, help="提示順を決める乱数の種（評価者ごとに変えてもよい）")
    s.add_argument("--split", choices=["pilot", "eval", "dev"])
    s.add_argument("--criteria", default="configs/care/criteria_v0.2_time.md", help="xlsx に載せる判定基準")
    s.set_defaults(func=human_export)
    s = human.add_parser("import", help="記入済みの評価票を取り込む")
    s.add_argument("data")
    s.add_argument("sheet")
    s.add_argument("--annotator", required=True)
    s.add_argument("--out", help="保存先（省略時は data を上書き）")
    s.set_defaults(func=human_import)
    s = human.add_parser("agreement", help="評価者間の一致度を出す")
    s.add_argument("data")
    s.add_argument("--table", help="例ごとの一覧をCSVで保存")
    s.add_argument("--write-gold", help="全員一致の例に gold_label を付けて保存")
    s.set_defaults(func=human_agreement)

    gen = top.add_parser("gen", help="会話の生成").add_subparsers(dest="cmd", required=True)
    s = gen.add_parser("plan", help="生成する場面の組み合わせを表示")
    s.add_argument("config")
    s.set_defaults(func=gen_plan)
    s = gen.add_parser("run", help="生成する")
    s.add_argument("config")
    s.set_defaults(func=gen_run)
    s = gen.add_parser("show", help="生成した例を読みやすく表示")
    s.add_argument("data")
    s.add_argument("--scene")
    s.set_defaults(func=gen_show)

    fr = top.add_parser("friction", help="探索実験（会話全体の摩擦・視点条件）").add_subparsers(dest="cmd", required=True)
    s = fr.add_parser("validate")
    s.add_argument("config")
    s.set_defaults(func=friction_validate)
    s = fr.add_parser("show-prompt")
    s.add_argument("config")
    s.add_argument("--dialogue", required=True)
    s.add_argument("--condition", required=True)
    s.add_argument("--swap", action="store_true")
    s.set_defaults(func=friction_show_prompt)
    s = fr.add_parser("run")
    s.add_argument("config")
    s.add_argument("--out", default="results")
    s.add_argument("--resume")
    s.set_defaults(func=friction_run)
    s = fr.add_parser("analyze")
    s.add_argument("run_dir")
    s.set_defaults(func=friction_analyze)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
