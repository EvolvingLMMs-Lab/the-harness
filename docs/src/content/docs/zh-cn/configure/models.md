---
title: "模型和 provider"
description: "接入任意 provider 的托管模型，或你自己运行的模型，并选择由哪个模型做什么。"
---

agent 可以使用任何语言模型。每个 provider 的设置方式都一样：拿到密钥，交给 The Harness，再指定一个模型。

## 已保存的模型

终端中的 `/models` 打开模型清单，`/model` 选择模型。

直接编辑 `~/.harness/models.json`。设置了 `HARNESS_DATA` 时，文件在该目录下。

```json
[
  { "provider": "ollama", "model": "my-model", "name": "本地模型", "enabled": true }
]
```

自定义端点可填 `base_url`，支持推理档位时可在 `efforts` 中列出该模型的档位 ID。
未选择档位时使用服务商默认值。密钥仍通过服务商设置或环境变量管理。

## 设置和更换模型

第一次运行 `harness` 时，它会询问 provider、模型和密钥，向 provider 验证密钥，并把它们保存在 `~/.harness/config.toml` 中：

```toml
[model]
provider = "openrouter"
model = "deepseek/deepseek-v4.1-flash"
reasoning_effort = "low"           # optional: low, medium, high
# base_url = "https://..."         # another address for the provider, such as a proxy

[keys]
OPENROUTER_API_KEY = "sk-or-..."
```

要更换模型，可以编辑这个文件，或使用 app 中的 **Settings → Model**，它也会验证密钥，并列出 provider 提供的模型供你选择。环境变量中的密钥优先于
`[keys]`。`[model]` 还接受 `max_output_tokens`、`checker`（同一 provider 的另一个模型，用来检查结果）和 `think_while_acting`
（[设置参考](/docs/zh-cn/reference/settings/)）。

## Provider

| Provider | 密钥变量 | 地址 |
|---|---|---|
| OpenRouter | `OPENROUTER_API_KEY` | 一个密钥用于大多数模型（默认） |
| OpenAI | `OPENAI_API_KEY` | `https://api.openai.com/v1` |
| Anthropic | `ANTHROPIC_API_KEY` | `https://api.anthropic.com/v1` |
| Google Gemini | `GEMINI_API_KEY` | `https://generativelanguage.googleapis.com/v1beta/openai` |
| xAI | `XAI_API_KEY` | `https://api.x.ai/v1` |
| DeepSeek | `DEEPSEEK_API_KEY` | `https://api.deepseek.com/v1` |
| Qwen (DashScope) | `DASHSCOPE_API_KEY` | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| Zhipu GLM | `ZHIPU_API_KEY` | `https://open.bigmodel.cn/api/paas/v4` |
| Moonshot Kimi | `MOONSHOT_API_KEY` | `https://api.moonshot.cn/v1` |
| Ollama | 无 | `http://localhost:11434/v1` |
| Custom | `HARNESS_LLM_API_KEY` | 任何兼容 OpenAI 的服务器：vLLM、SGLang、LM Studio、网关 |

每个 provider 的步骤都相同：

1. **获取密钥**：在 provider 的控制台中获取。
2. **交给 The Harness**：在第一次运行 `harness` 时、在 `[keys]` 中、在 app 中，或作为 shell 中的变量
   （`export OPENROUTER_API_KEY=...`）。
3. **指定模型**：在 `[model]` 中，或在 benchmark 运行使用的模型文件中（见下文）。

## 模型文件

benchmark 的运行，以及任何需要为每个角色使用不同模型的运行，从**模型文件**读取模型，模型文件为 agent 的每个角色指定一个模型：

| 角色 | 作用 |
|---|---|
| `main` | 写 agent 的回复和程序 |
| `vlm` | 回答程序提出的关于图像的问题 |
| `pointer` | 在图像中指出目标 |
| `verifier` | 在 agent 结束前检查结果 |

只有 `main` 是必需的；`verifier` 沿用 `main` 的设置，再叠加它自己的设置。一个你自己的模型文件：

```toml
# my-model.toml
description = "Claude through Anthropic's API"

[main]
backend = "openai_chat"                    # any OpenAI-compatible endpoint
base_url = "https://api.anthropic.com/v1"
api_key_env = "ANTHROPIC_API_KEY"          # the variable that holds the key
model = "claude-sonnet-5-5"
reasoning_effort = "medium"
max_output_tokens = 8192
```

```bash
harness run experiment my-experiment.toml --model my-model.toml
```

`backend = "openrouter"`（默认）使用 OpenRouter，此时 `model` 是 OpenRouter 的 id，例如
`deepseek/deepseek-v4.1-flash`。一个角色的键：

| 键 | |
|---|---|
| `backend` | `openrouter`（默认）或 `openai_chat` |
| `model` | provider 的模型 id |
| `base_url`、`base_url_env` | 端点，或保存端点的变量 |
| `api_key_env` | 保存密钥的变量（默认 `OPENROUTER_API_KEY`） |
| `reasoning_effort` | `low`、`medium` 或 `high`，模型支持时有效 |
| `max_output_tokens`、`temperature` | 常见的采样限制 |
| `stream` | 流式返回回复；时间轴随之实时显示文本 |
| `timeout_seconds`、`retries`、`retry_seconds` | 等待多久，以及重试几次 |
| `extra_body` | 添加到每个请求中的字段，用于 provider 特有的选项 |
| `service` | 由 The Harness 自己运行的模型（见下文），代替托管模型 |

密钥只从环境变量读取，从不从文件读取。base URL 也可以来自环境变量（`base_url_env`），这样同一份配置可以指向另一台服务器，而不改变它的
identity。

## 在你自己电脑上的模型

**使用你自己运行的服务器**，例如 Ollama、vLLM、SGLang 或 LM Studio：在第一次运行时选择 **Ollama** 或
**Custom**（或在 `[model]` 中设置 `provider` 和 `base_url`），或者写一个模型文件，设置 `backend = "openai_chat"` 和它的 `base_url`：

```toml
[main]
backend = "openai_chat"
base_url = "http://localhost:11434/v1"
model = "qwen3-vl:32b"
api_key_env = "HARNESS_LLM_API_KEY"   # any value; the server ignores it
```

**或者让 The Harness 来运行它**：`local-models` 包提供模型服务，它们会自己安装环境和权重，并在运行需要时在 GPU 上启动。
角色可以指定这样一个服务，而不是托管模型：

```toml
[main]
service = "qwen3-vl-32b"
max_output_tokens = 2048
```

[服务](/docs/zh-cn/configure/services/)介绍了服务如何启动和停止。

## 把 coding agent 当作模型

支持 Agent Client Protocol 的 agent（Claude Code、Codex 以及 ACP Registry 里的其他 agent）可以当作模型用。这时由 Harness 的 agent 用它来做决策，和用其他模型一样：程序、工作区、学习和 library 都照常。agent 用它自己的方式登录，所以订阅账号不需要 provider 密钥。

```sh
harness install external-agents
harness agents update
harness agents ls
harness agents install ACP_REGISTRY_ID
```

在 `~/.harness/models.json` 里加一个条目。`model` 和 `efforts` 填这个 agent 在模型和推理档位选项里提供的值：

```json
[
  { "provider": "acp:ACP_REGISTRY_ID", "model": "MODEL", "name": "我的 agent", "enabled": true,
    "efforts": ["low", "high"] }
]
```

```sh
harness run "按日期重命名照片" --folder ./photos --model MODEL
```

每次调用是 agent 一个会话里的一轮，它输出的文本就是回复。agent 自己不做任何事：它拿到的是一个空目录，没有客户端能力，在它接受的情况下也没有内置工具；它的权限请求一律拒绝，如果某一轮它启动了自己的工具，这一轮算失败。延续对话的调用只把新消息发给 agent 的会话。历史被缩短或改写的调用，以及同时发出的第二个调用，各用一个新会话并发送完整对话。

agent 是否上报 token 和费用由它自己决定，所以费用上限只对上报费用的 agent 生效。订阅账号上报的费用是 agent 的估算，不是实际扣费。图片只发给声明能读图的 agent。

`--agent acp:ACP_REGISTRY_ID` 是另一回事：那是 agent 自己在一个目录里的对话，用它自己的工具（[外部 coding 会话](/docs/zh-cn/use/sessions/#外部-coding-会话)）。

## 不能读图的模型

模型不一定要能读图。每一轮都是文本，只有 agent 去看的时候才会发图（[多模态优先](/docs/zh-cn/concepts/multimodal/)）。模型列表记录每个模型能否读图：**查找模型**会在 provider 的目录给出时采用目录的说法，你也可以在**模型详情 → 能读图**里修改，或在 `~/.harness/models.json` 的条目上写 `"images": false`。没有这个标记的模型视为能读图。

不能读图的模型不会收到图：

- 在项目文件夹里或不用环境时，它和其他模型一样工作。
- 在有屏幕的环境里，它依靠状态、元素和页面文本工作。它去看的时候，由 `model.vision` 指定的视觉模型（同一 provider 的另一个模型）用文字描述画面；没有指定时，它会被告知画面没有发送。
- 选择对话在哪里工作时，有屏幕的环境旁边会事先注明这一点。

## 选择模型

- 按任务选模型。终端里、文件上或窗口元素上的工作是文本；游戏、画布或摄像头场景要靠图像了解，需要能读图的模型，或者在旁边配一个视觉模型（见下）。
- 推理强度低的快速模型能让 agent 保持响应及时；每当有新情况发生，它都会再次询问模型，所以许多短调用好过少数长调用。
- `[limits]` 用模型调用次数和分钟数限制一个对话。App 和终端不显示花费，也不设金额上限：只有 OpenRouter 会报告一次调用的花费。
- 子 agent 可以使用同一 provider 的另一个模型，作为更便宜或更强的帮手（[子 agent](/docs/zh-cn/use/sessions/#子-agent)）。
