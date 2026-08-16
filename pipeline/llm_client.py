"""Multi‑provider LLM client with fallback and rate‑limit handling."""
from __future__ import annotations

import json
import os
import re
import time
from typing import Any

import httpx

OLLAMA_URL = "http://localhost:11434/api/generate"

PROVIDERS = {
    "groq": {
        "api_key_env": "GROQ_API_KEY",
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "default_model": "llama3-8b-8192",
        "type": "openai",
    },
    "openai": {
        "api_key_env": "OPENAI_API_KEY",
        "url": "https://api.openai.com/v1/chat/completions",
        "default_model": "gpt-4o-mini",
        "type": "openai",
    },
    "ollama": {
        "api_key_env": None,
        "url": OLLAMA_URL,
        "default_model": "qwen3:8b",
        "type": "ollama",
    },
}

class LLMClient:
    def __init__(self, system_prompt: str = ""):
        """Initialize with a system prompt."""
        self.system_prompt = system_prompt

    def _get_available_providers(self) -> list[str]:
        providers = []
        for name, cfg in PROVIDERS.items():
            if name == "ollama":
                try:
                    with httpx.Client(timeout=2.0) as client:
                        resp = client.get("http://localhost:11434/api/tags")
                        if resp.status_code == 200:
                            providers.append(name)
                except Exception:
                    pass
            else:
                if os.getenv(cfg["api_key_env"]):
                    providers.append(name)
        priority = ["groq", "openai", "ollama"]
        return [p for p in priority if p in providers]

    def _call_provider(self, provider: str, prompt: str, model: str | None = None, timeout: float = 60.0) -> str:
        cfg = PROVIDERS[provider]
        if provider == "ollama":
            payload = {
                "model": model or cfg["default_model"],
                "prompt": prompt,
                "system": self.system_prompt,
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.3, "num_predict": 1024},
            }
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(cfg["url"], json=payload)
                resp.raise_for_status()
                return resp.json().get("response", "")
        else:
            headers = {
                "Authorization": f"Bearer {os.getenv(cfg['api_key_env'])}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": model or cfg["default_model"],
                "messages": [
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.3,
                "max_tokens": 1024,
            }
            if provider == "groq":
                payload["response_format"] = {"type": "json_object"}
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(cfg["url"], headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"]

    def complete_json(self, prompt: str, model: str | None = None, max_retries: int = 2) -> dict[str, Any]:
        providers = self._get_available_providers()
        if not providers:
            raise RuntimeError("No LLM providers available (set GROQ_API_KEY, OPENAI_API_KEY, or run Ollama)")

        last_error = None
        for provider in providers:
            for attempt in range(max_retries):
                try:
                    raw = self._call_provider(provider, prompt, model=model)
                    # Improved markdown stripping
                    cleaned = raw.strip()
                    cleaned = re.sub(r'^```(?:json)?\s*|\s*```$', '', cleaned, flags=re.IGNORECASE)
                    return json.loads(cleaned)
                except Exception as e:
                    last_error = e
                    time.sleep(1.0 * (attempt + 1))
        raise RuntimeError(f"All providers failed: {last_error}")