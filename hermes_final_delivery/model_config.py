"""Provider-aware writer-model configuration."""

from __future__ import annotations

import threading
from typing import Any


def normalize_provider(value: Any) -> str:
    """Normalize the provider identity supplied by Hermes middleware."""
    return str(value or "").strip().casefold()


class WriterModelConfig:
    """Read and update this plugin's profile-scoped model routing settings."""

    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx
        self._write_lock = threading.Lock()

    def provider_models(self) -> dict[str, str]:
        raw = self.ctx.get_config("writer_models", {})
        if not isinstance(raw, dict):
            return {}
        models: dict[str, str] = {}
        for provider, model in raw.items():
            if not isinstance(provider, str) or not isinstance(model, str):
                continue
            key = normalize_provider(provider)
            value = model.strip()
            if key and value:
                models[key] = value
        return models

    def default_model(self) -> str:
        """Return the legacy/default fallback used when no provider route matches."""
        raw = self.ctx.get_config("writer_model", "")
        return raw.strip() if isinstance(raw, str) else ""

    def has_any(self) -> bool:
        return bool(self.default_model() or self.provider_models())

    def resolve(self, provider: Any) -> str | None:
        key = normalize_provider(provider)
        if key:
            model = self.provider_models().get(key)
            if model:
                return model
        return self.default_model() or None

    def set_provider_model(self, provider: Any, model: Any) -> tuple[str, str]:
        key = normalize_provider(provider)
        value = str(model or "").strip()
        if not key:
            raise ValueError("provider must not be empty")
        if not value:
            raise ValueError("model must not be empty")
        with self._write_lock:
            models = self.provider_models()
            models[key] = value
            self.ctx.set_config("writer_models", models)
        return key, value

    def unset_provider_model(self, provider: Any) -> tuple[str, bool]:
        key = normalize_provider(provider)
        if not key:
            raise ValueError("provider must not be empty")
        with self._write_lock:
            models = self.provider_models()
            removed = models.pop(key, None) is not None
            self.ctx.set_config("writer_models", models)
        return key, removed

    def set_default_model(self, model: Any) -> str:
        value = str(model or "").strip()
        if not value:
            raise ValueError("model must not be empty")
        with self._write_lock:
            self.ctx.set_config("writer_model", value)
        return value

    def clear_default_model(self) -> bool:
        with self._write_lock:
            had_default = bool(self.default_model())
            self.ctx.set_config("writer_model", "")
        return had_default
