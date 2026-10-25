"""LLMバックエンド（判定・知識整理・会話生成で共通）。

- anthropic: Claude API を呼ぶ（環境変数 ANTHROPIC_API_KEY が必要）
- manual: APIを使わず、プロンプトをファイルに書き出す。ChatGPTやClaudeの画面に貼り付けて得た回答を
  ファイルに保存して再実行すると、その回答を読み込んで続きを進める
- mock: APIを呼ばずにJSONスキーマに合うランダムな値を返す。パイプラインの動作確認専用で、結果に意味はない
"""

from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

# fallbacks="default" に対応するモデル
_FALLBACK_MODELS = {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}


class ModelConfig(BaseModel):
    backend: Literal["anthropic", "manual", "mock"] = "mock"
    name: str = "claude-opus-5-5"
    effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    max_tokens: int = 16000
    use_fallbacks: bool = True  # 安全分類器による拒否時に別モデルで再実行（対応モデルのみ）
    max_workers: int = 4  # 並列リクエスト数
    manual_dir: str | None = None  # manual のやり取り用フォルダ（省略時は実行ディレクトリ内の manual/）


@dataclass
class LLMResult:
    text: str
    model: str  # 実際に応答したモデル（フォールバック時は元と異なる）
    stop_reason: str
    usage: dict = field(default_factory=dict)


class PendingResponse(Exception):
    """manual バックエンドで、まだ回答ファイルが用意されていないことを表す。"""


def sample_from_schema(schema: dict, rng: random.Random):
    """JSONスキーマに合う値をランダムに作る（mock用）。"""
    if "enum" in schema:
        return rng.choice(schema["enum"])
    t = schema.get("type")
    if t == "object":
        return {k: sample_from_schema(v, rng) for k, v in schema.get("properties", {}).items()}
    if t == "array":
        lo = schema.get("minItems", 0)
        hi = max(lo, min(schema.get("maxItems", 3), 3))
        return [sample_from_schema(schema["items"], rng) for _ in range(rng.randint(lo, hi))]
    if t == "boolean":
        return rng.random() < 0.5
    if t == "integer":
        return rng.randint(schema.get("minimum", 0), schema.get("maximum", 3))
    if t == "string":
        return f"（mock出力{rng.randint(0, 9999)}）"
    return None


class MockBackend:
    def __init__(self, cfg: ModelConfig):
        self.cfg = cfg

    def generate_json(self, system: str, user: str, schema: dict, seed: str) -> LLMResult:
        out = sample_from_schema(schema, random.Random(seed))
        return LLMResult(json.dumps(out, ensure_ascii=False), "mock", "end_turn")


class ManualBackend:
    """<manual_dir>/<seed>.prompt.md を書き出し、<manual_dir>/<seed>.response.txt があれば読む。"""

    def __init__(self, cfg: ModelConfig):
        self.dir = Path(cfg.manual_dir)
        self.dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _safe(seed: str) -> str:
        return "".join(c if c.isalnum() or c in "-_." else "_" for c in seed)

    def generate_json(self, system: str, user: str, schema: dict, seed: str) -> LLMResult:
        name = self._safe(seed)
        resp = self.dir / f"{name}.response.txt"
        if resp.exists() and resp.read_text(encoding="utf-8").strip():
            text = resp.read_text(encoding="utf-8").strip()
            # 画面からコピーしたときに付きがちな ```json ... ``` を外す
            if text.startswith("```"):
                text = text.strip("`").removeprefix("json").strip()
            return LLMResult(text, "manual", "end_turn")
        prompt = (
            f"{system}\n\n{user}\n\n"
            "---\n回答は次のJSONスキーマに従うJSONだけを出力してください。\n"
            f"```json\n{json.dumps(schema, ensure_ascii=False, indent=1)}\n```\n"
        )
        (self.dir / f"{name}.prompt.md").write_text(prompt, encoding="utf-8")
        raise PendingResponse(str(resp))


class AnthropicBackend:
    def __init__(self, cfg: ModelConfig):
        import anthropic

        self.cfg = cfg
        # 認証情報は環境変数 ANTHROPIC_API_KEY などから自動で読まれる
        self.client = anthropic.Anthropic(max_retries=4)

    def generate_json(self, system: str, user: str, schema: dict, seed: str) -> LLMResult:
        kwargs = dict(
            model=self.cfg.name,
            max_tokens=self.cfg.max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={
                "effort": self.cfg.effort,
                "format": {"type": "json_schema", "schema": schema},
            },
        )
        if self.cfg.use_fallbacks and self.cfg.name in _FALLBACK_MODELS:
            resp = self.client.beta.messages.create(
                betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs
            )
        else:
            resp = self.client.messages.create(**kwargs)

        text = "".join(b.text for b in resp.content if b.type == "text")
        u = resp.usage
        usage = {"input_tokens": u.input_tokens, "output_tokens": u.output_tokens}
        return LLMResult(text, resp.model, resp.stop_reason or "", usage)


def make_backend(cfg: ModelConfig):
    return {"mock": MockBackend, "manual": ManualBackend, "anthropic": AnthropicBackend}[cfg.backend](cfg)


def call_with_retry(fn, attempts: int = 3, base_delay: float = 5.0):
    """SDK自体も再試行するが、長時間の混雑に備えて外側でももう少し粘る。"""
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:
            retryable = type(e).__name__ in {
                "RateLimitError", "APIConnectionError", "APITimeoutError", "InternalServerError",
            }
            if not retryable or i == attempts - 1:
                raise
            time.sleep(base_delay * 2**i)


def check_result(res: LLMResult) -> str | None:
    """応答が使えない場合の理由を返す（使える場合は None）。"""
    if res.stop_reason == "refusal":
        return "refusal"
    if res.stop_reason == "max_tokens":
        return "max_tokens"
    return None
