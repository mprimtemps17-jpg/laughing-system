"""コマンドライン入口。

  python -m frictionlab validate configs/experiment.yaml
  python -m frictionlab show-prompt configs/experiment.yaml --dialogue ex01 --condition pov_B_private
  python -m frictionlab run configs/experiment.yaml [--resume results/<run>]
  python -m frictionlab analyze results/<run>
"""

from __future__ import annotations

import argparse
import sys

from .config import config_warnings, load_experiment, load_taxonomy
from .data import load_dialogues


def cmd_validate(args) -> int:
    cfg = load_experiment(args.config)
    ds = load_dialogues(cfg.data)
    tax = load_taxonomy(cfg.taxonomy)
    ids = {c.id for c in tax}
    n_lab = sum(d.human_label is not None for d in ds)
    print(f"設定OK: {cfg.name} / 条件 {len(cfg.conditions)} 個 / 要因分類 {len(tax)} 個")
    print(f"データOK: 会話 {len(ds)} 件（人間ラベル付き {n_lab} 件）")
    for c in cfg.conditions:
        diff = cfg.diff_from_reference(c)
        d = "基準" if c.name == cfg.baseline else (
            f"vs {cfg.reference_of(c)}: " + ", ".join(f"{k} {a}→{b}" for k, (a, b) in diff.items())
        )
        print(f"  - {c.name:<24} [{d}] {c.description}")
    for d in ds:
        if d.human_label:
            unknown = set(d.human_label.causes) - ids
            if unknown:
                print(f"[注意] {d.id}: 分類にない要因ID {sorted(unknown)}")
    for w in config_warnings(cfg):
        print(f"[注意] {w}")
    swaps = 2 if cfg.swap_speakers else 1
    n = (min(len(ds), cfg.limit) if cfg.limit else len(ds)) * len(cfg.conditions) * cfg.repeats * swaps
    print(f"実行すると {n} 回LLMを呼び出します（backend={cfg.model.backend}, model={cfg.model.name}）")
    return 0


def cmd_show_prompt(args) -> int:
    from .prompts import build_prompt

    cfg = load_experiment(args.config)
    d = next((x for x in load_dialogues(cfg.data) if x.id == args.dialogue), None)
    if d is None:
        print(f"会話 '{args.dialogue}' が見つかりません", file=sys.stderr)
        return 1
    system, user = build_prompt(d, cfg.condition(args.condition), load_taxonomy(cfg.taxonomy), args.swap)
    print("=== system ===\n" + system + "\n\n=== user ===\n" + user)
    return 0


def cmd_run(args) -> int:
    from .runner import run_experiment

    cfg = load_experiment(args.config)
    out = run_experiment(cfg, args.config, out_root=args.out, resume=args.resume)
    print(f"完了: {out}\n次に: python -m frictionlab analyze {out}")
    return 0


def cmd_analyze(args) -> int:
    from .analysis import analyze

    print(f"レポート: {analyze(args.run_dir)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="frictionlab", description="会話の摩擦判定実験")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("validate", help="設定とデータを検査し、呼び出し回数を表示する")
    s.add_argument("config")
    s.set_defaults(func=cmd_validate)

    s = sub.add_parser("show-prompt", help="実際にLLMへ送るプロンプトを表示する")
    s.add_argument("config")
    s.add_argument("--dialogue", required=True)
    s.add_argument("--condition", required=True)
    s.add_argument("--swap", action="store_true", help="A/Bラベルを入れ替えた版を表示")
    s.set_defaults(func=cmd_show_prompt)

    s = sub.add_parser("run", help="実験を実行する")
    s.add_argument("config")
    s.add_argument("--out", default="results")
    s.add_argument("--resume", help="既存の実行ディレクトリの続きから実行する")
    s.set_defaults(func=cmd_run)

    s = sub.add_parser("analyze", help="実行結果を分析してレポートを作る")
    s.add_argument("run_dir")
    s.set_defaults(func=cmd_analyze)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
