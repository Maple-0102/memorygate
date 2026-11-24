"""Model adapter: one interface, swappable backends, every call logged with tokens and cost.

The rest of the code only sees `LLMClient.generate()`. Changing model or backend is a config edit.
"""
from __future__ import annotations

import json
import os
import random
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass
class Completion:
    text: str
    input_tokens: int = 0
    cached_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0
    latency_s: float = 0.0
    model: str = ""


class LLMClient(Protocol):
    model: str

    def generate(self, prompt: str, system: str | None = None, json_mode: bool = False,
                 max_tokens: int | None = None) -> Completion: ...


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class Pricing:
    input: float  # USD per 1M tokens
    cached_input: float
    output: float

    def cost(self, c: Completion) -> float:
        uncached = max(c.input_tokens - c.cached_tokens, 0)
        out = c.output_tokens + c.thinking_tokens  # thinking is billed as output
        return (uncached * self.input + c.cached_tokens * self.cached_input + out * self.output) / 1e6


@dataclass
class UsageMeter:
    """Wraps a client: enforces call/USD caps and appends one JSON line per call."""

    client: LLMClient
    pricing: Pricing
    log_path: Path | None = None
    max_calls: int | None = None
    max_usd: float | None = None
    calls: int = 0
    usd: float = 0.0
    totals: dict = field(default_factory=lambda: {"input": 0, "cached": 0, "output": 0, "thinking": 0})
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _inflight: int = 0

    def generate(self, prompt: str, system: str | None = None, tag: str = "", json_mode: bool = False,
                 max_tokens: int | None = None) -> Completion:
        """Thread-safe. In-flight calls count against the call cap, so concurrency cannot overshoot it."""
        with self._lock:
            if self.max_calls is not None and self.calls + self._inflight >= self.max_calls:
                raise BudgetExceeded(f"call cap reached ({self.max_calls})")
            if self.max_usd is not None and self.usd >= self.max_usd:
                raise BudgetExceeded(f"USD cap reached (${self.usd:.4f} >= ${self.max_usd})")
            self._inflight += 1
        try:
            c = self.client.generate(prompt, system, json_mode=json_mode, max_tokens=max_tokens)
        finally:
            with self._lock:
                self._inflight -= 1
        cost = self.pricing.cost(c)
        with self._lock:
            self.calls += 1
            self.usd += cost
            self.totals["input"] += c.input_tokens
            self.totals["cached"] += c.cached_tokens
            self.totals["output"] += c.output_tokens
            self.totals["thinking"] += c.thinking_tokens
            if self.log_path:
                self.log_path.parent.mkdir(parents=True, exist_ok=True)
                rec = {"ts": time.time(), "tag": tag, "cost_usd": cost, **asdict(c)}
                rec.pop("text")
                with open(self.log_path, "a") as f:
                    f.write(json.dumps(rec) + "\n")
        return c

    def summary(self) -> dict:
        return {"calls": self.calls, "usd": round(self.usd, 6), **self.totals}


class FakeClient:
    """Deterministic offline stub. `responder(prompt) -> text`; default echoes a fixed SQL."""

    def __init__(self, responder=None, model: str = "fake"):
        self.model = model
        self.responder = responder or (lambda p: "```sql\nSELECT 1\n```")

    def generate(self, prompt: str, system: str | None = None, json_mode: bool = False,
                 max_tokens: int | None = None) -> Completion:
        text = self.responder(prompt)
        return Completion(text=text, input_tokens=len(prompt) // 4, output_tokens=len(text) // 4, model=self.model)


class GeminiClient:
    """Gemini via the google-genai SDK, on Vertex AI or the Developer API (AI Studio)."""

    def __init__(self, mcfg: dict, backend: str):
        from google import genai
        from google.genai import types

        self._types = types
        self.model = mcfg["name"]
        if backend == "vertex":
            project = os.environ.get("GOOGLE_CLOUD_PROJECT")
            if not project:
                raise RuntimeError("set GOOGLE_CLOUD_PROJECT (and run `gcloud auth application-default login`)")
            self._client = genai.Client(vertexai=True, project=project, location=mcfg.get("location", "global"),
                                        http_options=types.HttpOptions(timeout=int(mcfg.get("timeout_s", 60)) * 1000))
        elif backend == "aistudio":
            key = os.environ.get("GEMINI_API_KEY")
            if not key:
                raise RuntimeError("set GEMINI_API_KEY")
            self._client = genai.Client(api_key=key, http_options=types.HttpOptions(timeout=int(mcfg.get("timeout_s", 60)) * 1000))
        else:
            raise ValueError(backend)

        thinking = None
        if mcfg.get("thinking_level"):
            thinking = types.ThinkingConfig(thinking_level=mcfg["thinking_level"])
        elif mcfg.get("thinking_budget") is not None and mcfg.get("thinking_budget") != "":
            thinking = types.ThinkingConfig(thinking_budget=int(mcfg["thinking_budget"]))
        self._base = dict(
            temperature=mcfg.get("temperature", 0.0),
            max_output_tokens=mcfg.get("max_output_tokens", 1024),
        )
        if thinking is not None:
            self._base["thinking_config"] = thinking
        self._throttle = _Throttle(float(mcfg.get("max_rps", 0) or 0))

    def generate(self, prompt: str, system: str | None = None, json_mode: bool = False,
                 max_tokens: int | None = None) -> Completion:
        kw = dict(self._base)
        if max_tokens:
            kw["max_output_tokens"] = max_tokens
        if json_mode:
            kw["response_mime_type"] = "application/json"
        cfg = self._types.GenerateContentConfig(system_instruction=system, **kw)
        self._throttle.wait()
        t0 = time.time()
        resp = _with_retry(lambda: self._client.models.generate_content(model=self.model, contents=prompt, config=cfg))
        um = resp.usage_metadata
        return Completion(
            text=resp.text or "",
            input_tokens=getattr(um, "prompt_token_count", 0) or 0,
            cached_tokens=getattr(um, "cached_content_token_count", 0) or 0,
            output_tokens=getattr(um, "candidates_token_count", 0) or 0,
            thinking_tokens=getattr(um, "thoughts_token_count", 0) or 0,
            latency_s=time.time() - t0,
            model=self.model,
        )


def _with_retry(fn, tries: int = 10):
    """Retry rate-limit and server errors with capped exponential backoff (up to ~8 minutes in total)."""
    for i in range(tries):
        try:
            return fn()
        except Exception as e:  # SDK raises various error types; retry only on rate limit / server errors
            code = getattr(e, "code", None) or getattr(e, "status_code", None)
            transient = code in (408, 429, 500, 502, 503, 504) or _is_network_error(e)
            if not transient or i == tries - 1:
                raise
            time.sleep(min(90, 2 ** (i + 1)) * (0.5 + random.random()))


def _is_network_error(e: Exception) -> bool:
    """Timeouts and dropped connections (httpx / httpcore / builtin), which are worth retrying."""
    names = {c.__name__ for c in type(e).__mro__}
    return bool(names & {"TimeoutException", "ReadTimeout", "ConnectTimeout", "WriteTimeout", "PoolTimeout",
                         "NetworkError", "ReadError", "ConnectError", "RemoteProtocolError", "TimeoutError",
                         "ConnectionError"})


class _Throttle:
    """Spaces out call starts within one process to at most `rps` per second."""

    def __init__(self, rps: float):
        self.interval = 1.0 / rps if rps and rps > 0 else 0.0
        self.next_t = 0.0
        self.lock = threading.Lock()

    def wait(self) -> None:
        if not self.interval:
            return
        with self.lock:
            now = time.monotonic()
            t = max(now, self.next_t)
            self.next_t = t + self.interval
        if t > now:
            time.sleep(t - now)


def make_client(cfg: dict, log_path: Path | None = None) -> UsageMeter:
    m = cfg["model"]
    provider = m["provider"]
    client: LLMClient = FakeClient() if provider == "fake" else GeminiClient(m, provider)
    p = cfg["pricing"]
    b = cfg.get("budget", {})
    return UsageMeter(
        client=client,
        pricing=Pricing(p["input"], p["cached_input"], p["output"]),
        log_path=log_path,
        max_calls=b.get("max_calls"),
        max_usd=b.get("max_usd"),
    )
