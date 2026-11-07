# Hermes Final Delivery

[简体中文](README-zh.md)

A standalone Hermes plugin that lets the main agent explicitly hand one final response to a
more expressive model. It implements the **same-provider one-request route** (the “B route”):

1. The main model finishes and verifies a substantial task.
2. It calls `final_delivery` alone with a complete, user-ready `draft`.
3. The plugin changes only the next logical LLM request's `model` field and removes every tool
   definition/control field from that request.
4. The configured writer model streams the final response normally.
5. The route lease is consumed; all later requests use the main model again.

The plugin never changes Hermes' global/default model setting.

## Important constraint

`writer_model` must be reachable through the main agent's **current provider, client, and API
mode**. For example, two model IDs exposed by the same gateway can work. This plugin cannot use
an OpenAI client for one request and silently turn it into an Anthropic or unrelated-provider
client.

Because this is a main-loop route, the writer model receives the request's existing conversation
history, not only `draft`. Use models on a provider you trust for the current conversation.

## Configuration

Hermes Desktop can render these settings from `plugin.yaml`. The equivalent `config.yaml` entry
is:

```yaml
plugins:
  enabled:
    - hermes-final-delivery
  entries:
    hermes-final-delivery:
      settings:
        writer_model: "YOUR-SAME-PROVIDER-MODEL-ID"
        max_draft_chars: 20000
        pending_ttl_seconds: 300
```

`writer_model` is intentionally empty by default. Until it is configured, `final_delivery`
returns an error and tells the main model to send its own draft, rather than routing somewhere
unexpected.

## Safety and failure behavior

- The tool must be the only call in its assistant tool-call batch and can be attempted once per
  user turn. Tools used earlier in the same long-running turn are unaffected.
- The writer request has `tools`, `tool_choice`, `parallel_tool_calls`, and known legacy/native
  equivalents removed.
- If a provider nevertheless returns a structured tool call, the plugin blocks execution and the
  next logical request goes back to the default model.
- If the writer request errors, the lease is disarmed before Hermes retries, so a retry uses the
  default model. A non-retryable provider failure can still fail the turn; that is a limitation of
  the pure-plugin B route.
- Pending state contains IDs and the writer model only. Drafts, messages, credentials, and provider
  request bodies are not copied into plugin state or logs.
- Incomplete state expires and plugin unload/session completion clears it. Missing state always
  fails open to Hermes' default route.

## Development

Requires Python 3.11–3.14, matching Hermes.

```powershell
cd C:\Users\88888888\user-workshop\hermes-final-delivery
py -3.12 -m unittest discover -s tests -v
```

The suite uses only the standard library. It can also be run with `pytest` when available.

With the Hermes checkout available, validate through Hermes' real loader too:

```powershell
hermes plugins doctor C:\Users\88888888\user-workshop\hermes-final-delivery --ci
hermes plugins validate C:\Users\88888888\user-workshop\hermes-final-delivery
```

## Manual installation (not performed by this repository)

First run the validation commands above. Then copy this directory to the active profile's plugin
directory as `hermes-final-delivery` (normally
`$HOME\.hermes\plugins\hermes-final-delivery`), enable it, configure `writer_model`, and start a
new Hermes session:

```powershell
hermes plugins enable hermes-final-delivery
```

Do not enable the plugin until you have reviewed its code and selected a model served by the same
provider as the main agent. Existing sessions should be restarted so the tool set remains stable
for prompt caching.
