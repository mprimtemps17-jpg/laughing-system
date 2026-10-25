"""実験の実行。全ての判定を results/<run>/judgments.jsonl に1行ずつ記録する。

同じ run ディレクトリを指定して再実行すると、完了済みの判定は飛ばして続きから実行する
（API料金の節約と、途中で止まった場合の再開のため）。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import yaml

from .. import __version__
from .config import Condition, ExperimentConfig, config_warnings, load_taxonomy
from .data import Dialogue, load_dialogues
from ..llm import PendingResponse, call_with_retry, check_result, make_backend
from .prompts import PROMPT_VERSION, build_prompt, output_schema, prompt_hash


@dataclass(frozen=True)
class Job:
    dialogue: Dialogue
    condition: Condition
    repeat: int
    swapped: bool

    @property
    def key(self) -> str:
        return f"{self.dialogue.id}|{self.condition.name}|{self.repeat}|{int(self.swapped)}"


def parse_judgment(text: str, swapped: bool) -> dict:
    """モデル出力をパースし、ラベル入れ替え版なら caused_by を元の話者に戻す。"""
    j = json.loads(text)
    if swapped and j.get("caused_by") in ("A", "B"):
        j["caused_by"] = {"A": "B", "B": "A"}[j["caused_by"]]
    return j


def _git_commit() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except Exception:
        return None


def build_jobs(cfg: ExperimentConfig, dialogues: list[Dialogue]) -> list[Job]:
    swaps = [False, True] if cfg.swap_speakers else [False]
    return [
        Job(d, c, r, s)
        for d in dialogues
        for c in cfg.conditions
        for r in range(cfg.repeats)
        for s in swaps
    ]


def run_experiment(
    cfg: ExperimentConfig, config_path: str, out_root: str = "results", resume: str | None = None
) -> Path:
    for w in config_warnings(cfg):
        print(f"[注意] {w}")

    dialogues = load_dialogues(cfg.data)
    if cfg.limit:
        dialogues = dialogues[: cfg.limit]
    taxonomy = load_taxonomy(cfg.taxonomy)
    schema = output_schema(taxonomy)

    if resume:
        out = Path(resume)
    else:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        out = Path(out_root) / f"{stamp}_{cfg.name}"
        out.mkdir(parents=True)
        # 再現性のため、設定・分類・データのコピーと実行環境を保存
        shutil.copy(config_path, out / "config.yaml")
        shutil.copy(cfg.taxonomy, out / "taxonomy.yaml")
        shutil.copy(cfg.data, out / "data.jsonl")
        meta = {
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "frictionlab_version": __version__,
            "prompt_version": PROMPT_VERSION,
            "git_commit": _git_commit(),
            "model": cfg.model.model_dump(),
            "n_dialogues": len(dialogues),
        }
        (out / "meta.yaml").write_text(yaml.safe_dump(meta, allow_unicode=True), encoding="utf-8")

    path = out / "judgments.jsonl"
    done: set[str] = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            if rec.get("error") is None:
                done.add(rec["key"])

    jobs = [j for j in build_jobs(cfg, dialogues) if j.key not in done]
    total = len(jobs) + len(done)
    print(f"判定数: {total}（完了済み {len(done)}、今回実行 {len(jobs)}） 出力先: {out}")
    if cfg.model.backend == "mock":
        print("[注意] mockバックエンドです。結果はランダムで研究上の意味はありません。")

    if cfg.model.backend == "manual" and not cfg.model.manual_dir:
        cfg.model.manual_dir = str(out / "manual")
    backend = make_backend(cfg.model)
    lock = threading.Lock()

    def work(job: Job) -> dict:
        system, user = build_prompt(job.dialogue, job.condition, taxonomy, job.swapped)
        rec = {
            "key": job.key,
            "dialogue_id": job.dialogue.id,
            "condition": job.condition.name,
            "repeat": job.repeat,
            "swapped": job.swapped,
            "prompt_hash": prompt_hash(system, user),
            "requested_model": cfg.model.name if cfg.model.backend != "mock" else "mock",
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "error": None,
        }
        try:
            res = call_with_retry(lambda: backend.generate_json(system, user, schema, seed=job.key))
            rec.update(model=res.model, stop_reason=res.stop_reason, usage=res.usage, raw=res.text)
            rec["error"] = check_result(res)
            if rec["error"] is None:
                rec["judgment"] = parse_judgment(res.text, job.swapped)
        except PendingResponse:
            return None
        except Exception as e:
            rec["error"] = f"{type(e).__name__}: {e}"
        return rec

    n_err = n_pending = 0
    with ThreadPoolExecutor(max_workers=cfg.model.max_workers) as ex, path.open("a", encoding="utf-8") as f:
        futures = [ex.submit(work, j) for j in jobs]
        for i, fut in enumerate(as_completed(futures), 1):
            rec = fut.result()
            if rec is None:
                n_pending += 1
                continue
            n_err += rec["error"] is not None
            with lock:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                f.flush()
            if i % 10 == 0 or i == len(jobs):
                print(f"  {i}/{len(jobs)} 完了（エラー {n_err}）")

    if n_pending:
        print(
            f"[manual] {n_pending} 件の回答待ちです。{cfg.model.manual_dir}/ の *.prompt.md を貼り付けて、"
            f"回答を同名の *.response.txt に保存し、--resume {out} を付けて再実行してください。"
        )
    if n_err:
        print(f"[注意] {n_err} 件がエラーでした。同じコマンドに --resume {out} を付けると再実行します。")
    return out
