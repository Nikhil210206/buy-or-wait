"""Provider clients (Gemini, xAI Grok) with a token ledger.

Standard library only -- no SDK install required. Every call is recorded so
evaluation/usage_report.md reflects the run that actually produced output.csv.
Keys come from the environment; nothing is ever written back to disk.
"""
from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_dotenv(path: Path | None = None) -> None:
    p = path or (ROOT / ".env")
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


# USD per 1M tokens. Adjust if your billing tier differs; the report cites these.
PRICING = {
    "gemini-2.5-flash":     (0.30, 2.50),
    "gemini-2.5-pro":       (1.25, 10.00),
    "gemini-flash-latest":  (0.30, 2.50),
    "grok-4-fast":          (0.20, 0.50),
    "grok-4":               (3.00, 15.00),
}
DEFAULT_PRICE = (0.30, 2.50)


@dataclass
class Call:
    provider: str
    model: str
    purpose: str
    in_tokens: int
    out_tokens: int
    seconds: float


@dataclass
class Ledger:
    calls: list[Call] = field(default_factory=list)

    def add(self, c: Call) -> None:
        self.calls.append(c)

    def cost(self, c: Call) -> float:
        pin, pout = PRICING.get(c.model, DEFAULT_PRICE)
        return c.in_tokens / 1e6 * pin + c.out_tokens / 1e6 * pout

    def total_cost(self) -> float:
        return sum(self.cost(c) for c in self.calls)

    def save(self, path: Path) -> None:
        path.write_text(json.dumps([c.__dict__ for c in self.calls], indent=2), encoding="utf-8")

    def load(self, path: Path) -> None:
        if path.exists():
            self.calls = [Call(**d) for d in json.loads(path.read_text(encoding="utf-8"))]


LEDGER = Ledger()


class LLMError(RuntimeError):
    pass


def _post(url: str, payload: dict, headers: dict, timeout: int = 120) -> dict:
    body = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", **headers})
    last: Exception | None = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            detail = e.read().decode()[:400]
            if e.code in (429, 500, 502, 503, 504):
                last = LLMError(f"HTTP {e.code}: {detail}")
                time.sleep(2 ** attempt * 2)
                continue
            raise LLMError(f"HTTP {e.code}: {detail}") from e
        except Exception as e:                       # network hiccup
            last = e
            time.sleep(2 ** attempt)
    raise LLMError(f"request failed after retries: {last}")


# --------------------------------------------------------------------------- Gemini

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"


def gemini_models() -> list[str]:
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        return []
    try:
        with urllib.request.urlopen(f"{GEMINI_BASE}/models?key={key}&pageSize=200", timeout=30) as r:
            data = json.loads(r.read())
    except Exception:
        return []
    return [m["name"].split("/", 1)[1] for m in data.get("models", [])
            if "generateContent" in m.get("supportedGenerationMethods", [])]


def gemini(prompt: str, *, model: str, purpose: str, image: Path | None = None,
           schema: dict | None = None, temperature: float = 0.0) -> str:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise LLMError("GEMINI_API_KEY not set")
    parts: list[dict] = [{"text": prompt}]
    if image is not None:
        parts.insert(0, {"inline_data": {
            "mime_type": "image/png",
            "data": base64.b64encode(image.read_bytes()).decode(),
        }})
    gen: dict = {"temperature": temperature}
    if schema is not None:
        gen["response_mime_type"] = "application/json"
        gen["response_schema"] = schema
    t0 = time.time()
    out = _post(f"{GEMINI_BASE}/models/{model}:generateContent?key={key}",
                {"contents": [{"parts": parts}], "generationConfig": gen}, {})
    u = out.get("usageMetadata", {})
    LEDGER.add(Call("google", model, purpose, u.get("promptTokenCount", 0),
                    u.get("candidatesTokenCount", 0), round(time.time() - t0, 2)))
    try:
        return "".join(p.get("text", "") for p in out["candidates"][0]["content"]["parts"])
    except (KeyError, IndexError) as e:
        raise LLMError(f"unexpected Gemini response: {json.dumps(out)[:400]}") from e


# --------------------------------------------------------------------------- xAI

XAI_BASE = "https://api.x.ai/v1"


def xai_models() -> list[str]:
    key = os.environ.get("XAI_API_KEY", "")
    if not key:
        return []
    try:
        req = urllib.request.Request(f"{XAI_BASE}/models",
                                     headers={"Authorization": f"Bearer {key}"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return [m["id"] for m in json.loads(r.read()).get("data", [])]
    except Exception:
        return []


def xai(prompt: str, *, model: str, purpose: str, temperature: float = 0.0,
        json_mode: bool = True) -> str:
    key = os.environ.get("XAI_API_KEY")
    if not key:
        raise LLMError("XAI_API_KEY not set")
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    t0 = time.time()
    out = _post(f"{XAI_BASE}/chat/completions", payload, {"Authorization": f"Bearer {key}"})
    u = out.get("usage", {})
    LEDGER.add(Call("xai", model, purpose, u.get("prompt_tokens", 0),
                    u.get("completion_tokens", 0), round(time.time() - t0, 2)))
    return out["choices"][0]["message"]["content"]


def pick(preferred: list[str], available: list[str]) -> str | None:
    """First preferred model that the account can actually see."""
    for p in preferred:
        for a in available:
            if a == p or a.startswith(p):
                return a
    return available[0] if available else None
