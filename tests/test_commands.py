from __future__ import annotations

import argparse
import contextlib
import io
import unittest
from typing import Any

from hermes_final_delivery.commands import DeliveryModelCommands
from hermes_final_delivery.model_config import WriterModelConfig, normalize_provider


class ConfigContext:
    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = dict(config or {})

    def get_config(self, key: str, default: Any = None) -> Any:
        return self.config.get(key, default)

    def set_config(self, key: str, value: Any) -> None:
        self.config[key] = value


def test_provider_normalization_and_specific_precedence() -> None:
    ctx = ConfigContext(
        {
            "writer_models": {
                " OpenRouter ": "writer/specific",
                "invalid": "",
                42: "ignored",
            },
            "writer_model": "writer/fallback",
        }
    )
    config = WriterModelConfig(ctx)
    assert normalize_provider(" OpenRouter ") == "openrouter"
    assert config.provider_models() == {"openrouter": "writer/specific"}
    assert config.resolve("OPENROUTER") == "writer/specific"
    assert config.resolve("anthropic") == "writer/fallback"

    malformed = WriterModelConfig(ConfigContext({"writer_model": {"bad": "shape"}}))
    assert malformed.default_model() == ""


def test_shared_command_updates_and_lists_routes() -> None:
    ctx = ConfigContext()
    commands = DeliveryModelCommands(WriterModelConfig(ctx))

    assert commands.execute(["set", "OpenRouter", "writer/model"]).ok
    assert ctx.config["writer_models"] == {"openrouter": "writer/model"}
    assert commands.execute(["default", "fallback/model"]).ok

    status = commands.handle_slash("list")
    assert "openrouter: writer/model" in status
    assert "Fallback for unmatched providers: fallback/model" in status

    assert commands.execute(["unset", "OPENROUTER"]).ok
    assert ctx.config["writer_models"] == {}
    assert commands.execute(["clear-default"]).ok
    assert ctx.config["writer_model"] == ""


def test_invalid_command_returns_usage_without_changing_config() -> None:
    ctx = ConfigContext()
    result = DeliveryModelCommands(WriterModelConfig(ctx)).execute(
        ["set", "openrouter"]
    )
    assert not result.ok
    assert result.text.startswith("Usage:")
    assert ctx.config == {}


def test_terminal_parser_uses_the_same_configuration_logic() -> None:
    ctx = ConfigContext()
    commands = DeliveryModelCommands(WriterModelConfig(ctx))
    parser = argparse.ArgumentParser()
    commands.setup_cli(parser)
    args = parser.parse_args(["set", "ollama", "qwen3:14b"])
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        exit_code = commands.handle_cli(args)
    assert exit_code == 0
    assert ctx.config["writer_models"] == {"ollama": "qwen3:14b"}
    assert "Set ollama" in output.getvalue()


def load_tests(loader, tests, pattern):  # noqa: ARG001
    suite = unittest.TestSuite()
    for name, value in sorted(globals().items()):
        if name.startswith("test_") and callable(value):
            suite.addTest(unittest.FunctionTestCase(value, description=name))
    return suite
