"""Shared slash-command and terminal-CLI configuration surface."""

from __future__ import annotations

import argparse
import shlex
import sys
from dataclasses import dataclass
from typing import Sequence

from .model_config import WriterModelConfig

COMMAND_NAME = "final-delivery-model"
COMMAND_DESCRIPTION = "Configure final-delivery writer models by provider"

USAGE = """Usage:
  final-delivery-model list
  final-delivery-model set <provider> <model>
  final-delivery-model unset <provider>
  final-delivery-model default <model>
  final-delivery-model clear-default"""


@dataclass(frozen=True, slots=True)
class CommandResult:
    text: str
    ok: bool = True


class DeliveryModelCommands:
    def __init__(self, config: WriterModelConfig) -> None:
        self.config = config

    def execute(self, argv: Sequence[str]) -> CommandResult:
        parts = list(argv)
        action = parts[0].casefold() if parts else "list"
        try:
            if action in {"list", "status"} and len(parts) == 1:
                return CommandResult(self._status())
            if action == "set" and len(parts) == 3:
                provider, model = self.config.set_provider_model(parts[1], parts[2])
                return CommandResult(f"Set {provider} final-delivery model to {model}.")
            if action == "unset" and len(parts) == 2:
                provider, removed = self.config.unset_provider_model(parts[1])
                if removed:
                    return CommandResult(
                        f"Removed the final-delivery model for {provider}."
                    )
                return CommandResult(
                    f"No final-delivery model was configured for {provider}."
                )
            if action == "default" and len(parts) == 2:
                model = self.config.set_default_model(parts[1])
                return CommandResult(
                    f"Set the fallback final-delivery model to {model}."
                )
            if action == "clear-default" and len(parts) == 1:
                removed = self.config.clear_default_model()
                text = (
                    "Removed the fallback final-delivery model."
                    if removed
                    else "No fallback final-delivery model was configured."
                )
                return CommandResult(text)
            if action in {"help", "-h", "--help"}:
                return CommandResult(USAGE)
        except Exception as exc:
            return CommandResult(
                f"Could not update final-delivery configuration: {exc}", ok=False
            )
        return CommandResult(USAGE, ok=False)

    def handle_slash(self, raw_args: str) -> str:
        try:
            argv = shlex.split(raw_args or "")
        except ValueError as exc:
            return f"Could not parse command: {exc}\n\n{USAGE}"
        return self.execute(argv).text

    def setup_cli(self, parser: argparse.ArgumentParser) -> None:
        subcommands = parser.add_subparsers(dest="final_delivery_model_command")
        subcommands.add_parser(
            "list", aliases=["status"], help="Show configured model routes"
        )

        set_parser = subcommands.add_parser("set", help="Set a model for one provider")
        set_parser.add_argument(
            "provider", help="Hermes provider ID, for example openrouter"
        )
        set_parser.add_argument("model", help="Model ID exposed by that provider")

        unset_parser = subcommands.add_parser("unset", help="Remove one provider route")
        unset_parser.add_argument("provider", help="Hermes provider ID")

        default_parser = subcommands.add_parser(
            "default", help="Set the fallback used when no provider route matches"
        )
        default_parser.add_argument("model", help="Fallback model ID")
        subcommands.add_parser("clear-default", help="Remove the fallback model")

    def handle_cli(self, args: argparse.Namespace) -> int:
        action = getattr(args, "final_delivery_model_command", None) or "list"
        argv = [action]
        if action == "set":
            argv.extend([args.provider, args.model])
        elif action == "unset":
            argv.append(args.provider)
        elif action == "default":
            argv.append(args.model)
        result = self.execute(argv)
        print(result.text, file=sys.stdout if result.ok else sys.stderr)
        return 0 if result.ok else 2

    def _status(self) -> str:
        models = self.config.provider_models()
        lines = ["Final-delivery models by provider:"]
        if models:
            lines.extend(
                f"  {provider}: {model}" for provider, model in sorted(models.items())
            )
        else:
            lines.append("  (none)")
        lines.append(
            f"Fallback for unmatched providers: {self.config.default_model() or '(none)'}"
        )
        return "\n".join(lines)
