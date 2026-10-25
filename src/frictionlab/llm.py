"""LLMバックエンド。

- anthropic: Claude API を呼ぶ（環境変数 ANTHROPIC_API_KEY が必要）
- mock: APIを呼ばずにランダムな判定を返す。パイプラインの動作確認専用で、結果に意味はない
"""

from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass, field

from .config import ModelConfig

# fallbacks="default" に対応するモデル
_FALLBACK_MODELS = {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}


@dataclass
class LLMResult:
    text: str
    model: str  # 実際に応答したモデル（フォールバック時は元と異なる）
    stop_reason: str
    usage: dict = field(default_factory=dict)


class MockBackend:
    """プロンプトのハッシュから決定的に乱数を作り、それらしい形式の判定を返す。"""

    def __init__(self, cfg: ModelConfig):
        self.cfg = cfg

    def judge(self, system: str, user: str, schema: dict, seed: str) -> LLMResult:
        rng = random.Random(seed)
        causes = schema["properties"]["causes"]["items"]["enum"]
        friction = rng.random() < 0.5
        out = {
            "friction": friction,
            "severity": rng.randint(1, 3) if friction else 0,
            "friction_turns": sorted(rng.sample(range(1, 7), k=rng.randint(1, 2))) if friction else [],
            "caused_by": rng.choice(["A", "B", "both"]) if friction else "none",
            "causes": rng.sample(causes, k=rng.randint(1, 2)) if friction else [],
            "rationale": "（mockバックエンドによるランダムな出力です）",
        }
        return LLMResult(json.dumps(out, ensure_ascii=False), "mock", "end_turn")


class AnthropicBackend:
    def __init__(self, cfg: ModelConfig):
        import anthropic

        self.cfg = cfg
        self.anthropic = anthropic
        # 認証情報は環境変数 ANTHROPIC_API_KEY などから自動で読まれる
        self.client = anthropic.Anthropic(max_retries=4)

    def judge(self, system: str, user: str, schema: dict, seed: str) -> LLMResult:
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
    if cfg.backend == "mock":
        return MockBackend(cfg)
    if cfg.backend == "anthropic":
        return AnthropicBackend(cfg)
    raise ValueError(f"unknown backend: {cfg.backend}")


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
