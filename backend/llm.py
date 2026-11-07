"""Клиенты LLM без внешних зависимостей (urllib).

Провайдер задаётся переменными окружения:
  CQA_LLM_PROVIDER = anthropic | openai | none
      openai — любой OpenAI-совместимый API: OpenAI, Groq, OpenRouter, Gemini (OpenAI-совместимый
      эндпоинт), локальная Ollama/LM Studio (CQA_LLM_BASE_URL=http://localhost:11434/v1).
  CQA_LLM_API_KEY, CQA_LLM_MODEL, CQA_LLM_BASE_URL
  CQA_PRICE_IN_PER_M, CQA_PRICE_OUT_PER_M — цена за 1M входных/выходных токенов в USD
      (для отчёта «стоимость одной оценки»).
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request


class LLMError(Exception):
    pass


def config() -> dict:
    provider = os.environ.get("CQA_LLM_PROVIDER", "").strip().lower()
    key = os.environ.get("CQA_LLM_API_KEY", "").strip()
    if not provider:
        if os.environ.get("ANTHROPIC_API_KEY"):
            provider, key = "anthropic", os.environ["ANTHROPIC_API_KEY"]
        elif os.environ.get("OPENAI_API_KEY"):
            provider, key = "openai", os.environ["OPENAI_API_KEY"]
        else:
            provider = "none"
    defaults = {
        "anthropic": ("https://api.anthropic.com", "claude-sonnet-5-5"),
        "openai": ("https://api.openai.com/v1", "gpt-4o-mini"),
    }
    base, model = defaults.get(provider, ("", ""))
    base_url = os.environ.get("CQA_LLM_BASE_URL", base).rstrip("/")
    is_local = base_url.startswith("http://localhost") or base_url.startswith("http://127.")
    return {
        "provider": provider,
        "model": os.environ.get("CQA_LLM_MODEL", model),
        "base_url": base_url,
        "api_key": key,
        "enabled": provider in ("anthropic", "openai") and (bool(key) or is_local),
        "price_in": float(os.environ.get("CQA_PRICE_IN_PER_M", "0") or 0),
        "price_out": float(os.environ.get("CQA_PRICE_OUT_PER_M", "0") or 0),
        "timeout": float(os.environ.get("CQA_LLM_TIMEOUT", "120")),
    }


def public_config() -> dict:
    c = config()
    return {"provider": c["provider"], "model": c["model"], "enabled": c["enabled"],
            "base_url": c["base_url"] if c["provider"] != "anthropic" else None,
            "price_in_per_m": c["price_in"], "price_out_per_m": c["price_out"]}


def _post(url, headers, body, timeout):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", **headers})
    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:500]
            last = LLMError(f"HTTP {e.code}: {detail}")
            if e.code in (429, 500, 502, 503, 529):
                time.sleep(2 * (attempt + 1))
                continue
            raise last
        except (urllib.error.URLError, TimeoutError) as e:
            last = LLMError(f"Сеть: {e}")
            time.sleep(2 * (attempt + 1))
    raise last


def chat(system: str, user: str, max_tokens: int = 4000) -> dict:
    """Возвращает {text, input_tokens, output_tokens, cost_usd, model}."""
    c = config()
    if not c["enabled"]:
        raise LLMError("LLM не настроен (CQA_LLM_PROVIDER / CQA_LLM_API_KEY)")
    if c["provider"] == "anthropic":
        resp = _post(f"{c['base_url']}/v1/messages",
                     {"x-api-key": c["api_key"], "anthropic-version": "2023-06-01"},
                     {"model": c["model"], "max_tokens": max_tokens, "temperature": 0,
                      "system": system, "messages": [{"role": "user", "content": user}]},
                     c["timeout"])
        text = "".join(b.get("text", "") for b in resp.get("content", []) if b.get("type") == "text")
        usage = resp.get("usage", {})
        tin, tout = usage.get("input_tokens", 0), usage.get("output_tokens", 0)
    else:
        headers = {"Authorization": f"Bearer {c['api_key']}"} if c["api_key"] else {}
        body = {"model": c["model"], "temperature": 0, "max_tokens": max_tokens,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        if os.environ.get("CQA_JSON_MODE", "1") == "1":
            body["response_format"] = {"type": "json_object"}
        try:
            resp = _post(f"{c['base_url']}/chat/completions", headers, body, c["timeout"])
        except LLMError as e:
            if "response_format" in str(e) and "response_format" in body:
                body.pop("response_format")
                resp = _post(f"{c['base_url']}/chat/completions", headers, body, c["timeout"])
            else:
                raise
        text = resp["choices"][0]["message"].get("content") or ""
        usage = resp.get("usage", {}) or {}
        tin, tout = usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)
    cost = (tin * c["price_in"] + tout * c["price_out"]) / 1_000_000
    return {"text": text, "input_tokens": tin, "output_tokens": tout,
            "cost_usd": round(cost, 6), "model": c["model"], "provider": c["provider"]}


def extract_json(text: str) -> dict:
    """Достаёт JSON-объект из ответа модели (учитывает ```json ... ``` и текст вокруг)."""
    t = text.strip()
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", t, re.S)
    if m:
        t = m.group(1)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    start = t.find("{")
    if start < 0:
        raise LLMError("В ответе модели нет JSON")
    depth, in_str, esc = 0, False, False
    for i in range(start, len(t)):
        ch = t[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(t[start:i + 1])
    raise LLMError("Не удалось разобрать JSON из ответа модели")
