"""主実験の実行。1例×1条件×1反復を1ジョブとし、results/<run>/judgments.jsonl に記録する。

- 各ジョブは独立した新しい呼び出しで行い、他の例や判定結果を履歴に含めない
- B・C は「整理→判定」の2回呼び出し。整理結果は誤っていても修正せずそのまま判定に使い、保存する
- 条件の実行順は例ごとに交替させ（A,B,C → B,C,A → ...）、その順序を記録する
- 同じ run を --resume で再実行すると、完了済みのジョブは飛ばす
"""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import yaml

from .. import __version__
from ..llm import PendingResponse, call_with_retry, check_result, make_backend
from .config import CONDITIONS, CareConfig
from .items import LABELS, CareItem, check_splits, load_items
from .prompts import PROMPT_VERSION, judge_prompt, organize_prompt


def _git_commit() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except Exception:
        return None


def select_items(cfg: CareConfig) -> list[CareItem]:
    items = load_items(cfg.data)
    if cfg.splits:
        items = [it for it in items if it.split in cfg.splits]
    return items[: cfg.limit] if cfg.limit else items


def plan_jobs(cfg: CareConfig, items: list[CareItem]) -> list[dict]:
    """実行順を固定した交替順で決める。"""
    jobs, order = [], 0
    k = len(cfg.conditions)
    for r in range(cfg.repeats):
        for i, it in enumerate(items):
            rot = cfg.conditions[i % k:] + cfg.conditions[: i % k]
            for cond in rot:
                jobs.append({"item": it, "condition": cond, "repeat": r, "order": order,
                             "key": f"{it.id}|{cond}|{r}"})
                order += 1
    return jobs


def _call(backend, system, user, schema, seed) -> tuple[dict, str | None]:
    t0 = time.time()
    res = call_with_retry(lambda: backend.generate_json(system, user, schema, seed=seed))
    rec = {"raw": res.text, "model": res.model, "stop_reason": res.stop_reason,
           "usage": res.usage, "elapsed_sec": round(time.time() - t0, 2)}
    err = check_result(res)
    if err is None:
        try:
            rec["parsed"] = json.loads(res.text)
        except json.JSONDecodeError:
            err = "format_error"
    return rec, err


def run_care(cfg: CareConfig, config_path: str, out_root: str = "results", resume: str | None = None) -> Path:
    items = select_items(cfg)
    for w in check_splits(load_items(cfg.data)):
        print(f"[注意] {w}")
    criteria = Path(cfg.criteria).read_text(encoding="utf-8")

    if resume:
        out = Path(resume)
    else:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        out = Path(out_root) / f"{stamp}_{cfg.name}"
        out.mkdir(parents=True)
        shutil.copy(config_path, out / "config.yaml")
        shutil.copy(cfg.criteria, out / "criteria.md")
        shutil.copy(cfg.data, out / "data.jsonl")
        meta = {
            "run_id": out.name,
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "experiment": "care",
            "frictionlab_version": __version__,
            "prompt_version": PROMPT_VERSION,
            "git_commit": _git_commit(),
            "model": cfg.model.model_dump(),
            "n_items": len(items),
        }
        (out / "meta.yaml").write_text(yaml.safe_dump(meta, allow_unicode=True), encoding="utf-8")

    path = out / "judgments.jsonl"
    done = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            if rec.get("error") is None:
                done.add(rec["key"])

    jobs = [j for j in plan_jobs(cfg, items) if j["key"] not in done]
    n_calls = sum(CONDITIONS[j["condition"]]["calls"] for j in jobs)
    print(f"判定: {len(jobs)} 件（完了済み {len(done)}）/ モデル呼び出し最大 {n_calls} 回 / 出力先: {out}")
    if cfg.model.backend == "mock":
        print("[注意] mockバックエンドです。結果はランダムで研究上の意味はありません。")
    if cfg.model.backend == "manual" and not cfg.model.manual_dir:
        cfg.model.manual_dir = str(out / "manual")
    backend = make_backend(cfg.model)

    def work(job: dict) -> dict | None:
        it, cond = job["item"], job["condition"]
        kind = CONDITIONS[cond]["organize"]
        rec = {"key": job["key"], "item_id": it.id, "scene_id": it.scene_id, "split": it.split,
               "variant": it.variant, "condition": cond, "repeat": job["repeat"], "order": job["order"],
               "started_at": datetime.now().isoformat(timespec="seconds"), "error": None}
        t0 = time.time()
        try:
            organized = None
            if kind:
                s, u, sc = organize_prompt(it, kind)
                rec["stage1"], err = _call(backend, s, u, sc, seed=f"{job['key']}|stage1")
                if err:
                    rec["error"] = f"stage1:{err}"
                    return rec
                organized = rec["stage1"]["parsed"]
            s, u, sc = judge_prompt(it, criteria, organized, kind)
            rec["final"], err = _call(backend, s, u, sc, seed=f"{job['key']}|final")
            if err is None and rec["final"]["parsed"].get("label") not in LABELS:
                err = "format_error"  # 手動で貼り付けた回答などで、ラベルが4つのどれでもない
            rec["error"] = err
            if err is None:
                rec["label"] = rec["final"]["parsed"]["label"]
        except PendingResponse:
            return None
        except Exception as e:
            rec["error"] = f"{type(e).__name__}: {e}"
        rec["elapsed_sec"] = round(time.time() - t0, 2)
        return rec

    lock = threading.Lock()
    counts = {"done": 0, "error": 0, "pending": 0}
    # ファイルを先に開き、全ジョブの終了（executor の終了）後に閉じる
    with path.open("a", encoding="utf-8") as f, ThreadPoolExecutor(max_workers=cfg.model.max_workers) as ex:
        def finish(fut):
            rec = fut.result()
            with lock:
                if rec is None:
                    counts["pending"] += 1
                    return
                counts["done"] += 1
                counts["error"] += rec["error"] is not None
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                f.flush()
                if counts["done"] % 10 == 0:
                    print(f"  {counts['done']} 件完了（エラー {counts['error']}）")

        for j in jobs:  # 計画した順に投入する（max_workers=1 なら完全にこの順）
            ex.submit(work, j).add_done_callback(finish)

    print(f"完了 {counts['done']} 件（エラー {counts['error']}）")
    if counts["pending"]:
        print(
            f"[manual] {counts['pending']} 件が回答待ちです。{cfg.model.manual_dir}/ の *.prompt.md を"
            "チャット画面に貼り付け、回答を同名の *.response.txt に保存してから、"
            f"--resume {out} を付けて再実行してください（B・Cは2段階なので2回繰り返します）。"
        )
    if counts["error"]:
        print(f"[注意] エラーは --resume {out} で再実行できます。")
    return out
