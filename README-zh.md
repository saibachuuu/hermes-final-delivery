# Hermes Final Delivery

[English](README.md)

这是一个独立的 Hermes 插件，让主 Agent 可以明确地将最后一条回复交给更善于表达的模型生成。插件实现的是**同 Provider 单请求路由**（即“B 路线”）：

1. 主模型完成并验证一项较复杂的任务。
2. 主模型单独调用 `final_delivery`，传入一份完整、可直接交付给用户的 `draft`。
3. 插件只修改下一个逻辑 LLM 请求的 `model` 字段，并移除该请求中的所有工具定义和工具控制字段。
4. 插件为当前 Provider 配置的表达模型正常以流式方式生成最终回复。
5. 一次性路由租约随即失效；后续所有请求重新使用主模型。

插件不会修改 Hermes 的全局或默认模型配置。

## 重要限制

`writer_models` 中的每个模型都必须能够通过对应 Provider **当前使用的客户端和 API 模式**访问。例如，同一网关提供的两个模型 ID 通常可以使用。本插件不能把原本发往 OpenAI 客户端的单次请求静默切换到 Anthropic 或其他无关 Provider 的客户端。

由于这是主循环内的请求路由，表达模型会收到该请求已有的完整对话历史，而不只是 `draft`。请仅选择你信任其处理当前对话内容的同 Provider 模型。

## 配置

Hermes Desktop 可以根据 `plugin.yaml` 自动生成设置界面。等价的 `config.yaml` 配置如下：

```yaml
plugins:
  enabled:
    - hermes-final-delivery
  entries:
    hermes-final-delivery:
      settings:
        writer_models:
          openrouter: "anthropic/claude-sonnet-4.5"
          ollama: "qwen3:14b"
        writer_model: "可选的回退模型-ID"
        max_draft_chars: 20000
        pending_ttl_seconds: 300
```

Provider ID 会统一转换为小写。当前 Provider 若匹配 `writer_models`，该项优先；`writer_model` 是没有专用项时使用的可选回退。所有路由默认故意留空。至少配置一项前，`final_delivery` 会返回错误并要求主模型自行发送草稿，而不会路由到未知位置。如果已有其他 Provider 的配置，但当前 Provider 没有匹配项或回退，本次交付会安全地留在默认模型上。只有当同一个模型 ID 在你使用的所有未映射 Provider 中都有效时，才应配置回退模型。

## 模型配置命令

插件始终注册可在 host 隔离模式下工作的会话内命令：

```text
/final-delivery-model list
/final-delivery-model set openrouter anthropic/claude-sonnet-4.5
/final-delivery-model unset openrouter
/final-delivery-model default fallback/model-id
/final-delivery-model clear-default
```

这些命令会更新当前 Profile 的插件设置。插件会在构建交付请求时读取映射，因此修改会从下一次交付开始生效，并且不会改变当前会话的工具集。

当 Hermes 让第三方插件在主进程中运行时，插件还会注册等价的终端命令：

```powershell
hermes final-delivery-model list
hermes final-delivery-model set openrouter anthropic/claude-sonnet-4.5
```

当配置为 `plugins.isolation: host` 时，Hermes 会有意跳过插件提供的
`hermes <command>`：本地 `argparse` 解析器无法跨越插件 Host 进程边界。此时请使用
`/final-delivery-model`，或通过 Hermes 的常规配置入口修改插件设置。修改配置的 Slash
命令会写入当前 Profile，因此只应允许受信任的用户执行。

## 安全与失败处理

- `final_delivery` 必须是其所在 assistant 工具调用批次中的唯一调用，并且每个用户回合最多尝试一次。同一长程任务中更早执行的工具不受影响。
- 表达模型请求会移除 `tools`、`tool_choice`、`parallel_tool_calls` 以及已知的旧版或 Provider 原生等价字段。
- 如果 Provider 仍然返回结构化工具调用，插件会阻止其执行，并让下一个逻辑请求回到默认模型。
- 如果表达模型请求报错，插件会在 Hermes 重试前解除路由租约，因此重试会使用默认模型。无法重试且没有回退路径的 Provider 错误仍可能导致本回合失败；这是纯插件 B 路线的已知限制。
- 临时状态只保存 ID 和表达模型名称，不会将草稿、消息、凭据或 Provider 请求正文复制到插件状态或日志中。
- 未完成状态会自动过期，并在会话结束或插件卸载时清理。状态缺失时始终回退到 Hermes 默认路由。

## 开发与测试

需要 Python 3.11–3.14，与 Hermes 的版本要求一致。

```powershell
cd C:\Users\88888888\user-workshop\hermes-final-delivery
py -3.12 -m unittest discover -s tests -v
```

测试套件仅使用 Python 标准库；如果环境中已安装 `pytest`，也可以使用它运行测试。

如果本机已有 Hermes checkout，还可以通过 Hermes 的真实插件加载器进行验证：

```powershell
hermes plugins doctor C:\Users\88888888\user-workshop\hermes-final-delivery --ci
hermes plugins validate C:\Users\88888888\user-workshop\hermes-final-delivery
```

## 手动安装（本仓库不会自动执行）

请先运行上面的验证命令。然后将本目录复制到当前 Profile 的插件目录，并命名为 `hermes-final-delivery`；默认位置通常是 `$HOME\.hermes\plugins\hermes-final-delivery`。随后启用插件、至少配置一项 `writer_models` 路由或 `writer_model` 回退，并新建一个 Hermes 会话：

```powershell
hermes plugins enable hermes-final-delivery
```

在审阅代码并选择与主 Agent 同 Provider 的模型前，请不要启用插件。启用插件后，应重新启动现有会话，以保持工具集和 Prompt Cache 稳定；仅修改模型映射无需重启会话。
