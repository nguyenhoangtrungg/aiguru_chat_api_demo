"""Configuration is loaded at startup, never from a chat request."""
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit
import math
import os

from dotenv import dotenv_values


@dataclass(frozen=True)
class Settings:
    base_url: str
    model: str
    api_key: str = field(default="", repr=False)
    timeout_seconds: float = 60.0

    @classmethod
    def load(cls, env_file: Path | None = None) -> "Settings":
        path = env_file if env_file is not None else Path(__file__).with_name(".env")
        values = {**dotenv_values(path, interpolate=False), **os.environ}

        def value(name: str, default: str = "") -> str:
            return (values.get(name) or default).strip()

        base_url = value("LLM_BASE_URL").rstrip("/")
        try:
            url = urlsplit(base_url)
            port = url.port
            valid = (url.scheme in {"http", "https"} and url.hostname
                     and not url.username and not url.password
                     and not url.query and not url.fragment
                     and not any(c.isspace() for c in base_url))
            if port is not None and port == 0:
                valid = False
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("LLM_BASE_URL must be an HTTP(S) base URL without credentials/query/fragment")
        if url.path.endswith("/chat/completions"):
            raise ValueError("LLM_BASE_URL must not include /chat/completions")
        model = value("LLM_MODEL")
        if not model or model.startswith("REPLACE_"):
            raise ValueError("LLM_MODEL must contain a real model ID")
        key = value("LLM_API_KEY")
        if key.startswith("REPLACE_") or "\n" in key or "\r" in key:
            raise ValueError("LLM_API_KEY must contain a valid single-line credential")
        if url.hostname == "openrouter.ai" and not key:
            raise ValueError("LLM_API_KEY is required for OpenRouter")
        try:
            timeout = float(value("LLM_TIMEOUT_SECONDS", "60"))
        except ValueError:
            raise ValueError("LLM_TIMEOUT_SECONDS must be a positive finite number") from None
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("LLM_TIMEOUT_SECONDS must be a positive finite number")
        return cls(base_url, model, key, timeout)
