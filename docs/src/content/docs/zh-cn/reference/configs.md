---
title: "模型、实验与 deploy 文件"
---

`configs/` 下除 agent 以外的文件。

<a id="models"></a>

## 模型

模型角色：`configs/models/<name>.toml`；通过 `--model NAME` 选择。

| 文件 | 说明 |
| --- | --- |
| `deepseek-api` | 通过 DeepSeek 自己的 API（DEEPSEEK_API_KEY）使用 DeepSeek V4.1 Flash 编写程序并回答图像问题 |
| `deepseek-flash` | DeepSeek V4.1 Flash 编写程序、回答图像问题并进行指点定位；pointer 角色使用 Molmo2 |
| `grok-low` | grok-4.7（low）编写程序、回答图像问题并进行指点定位；pointer 角色使用 Molmo2 |
| `grok-medium` | grok-4.7（medium）编写程序、回答图像问题并进行指点定位；pointer 角色使用 Molmo2 |
| `opus-5.5` | Claude Opus 5.5 编写程序、回答图像问题并进行指点定位；pointer 角色使用 Molmo2 |

<details>
<summary><code>configs/models/deepseek-api.toml</code></summary>

```toml
--8<-- "src/harness/builtin/configs/models/deepseek-api.toml"
```

</details>

<details>
<summary><code>configs/models/deepseek-flash.toml</code></summary>

```toml
--8<-- "src/harness/builtin/configs/models/deepseek-flash.toml"
```

</details>

<details>
<summary><code>configs/models/grok-low.toml</code></summary>

```toml
--8<-- "src/harness/builtin/configs/models/grok-low.toml"
```

</details>

<details>
<summary><code>configs/models/grok-medium.toml</code></summary>

```toml
--8<-- "src/harness/builtin/configs/models/grok-medium.toml"
```

</details>

<details>
<summary><code>configs/models/opus-5.5.toml</code></summary>

```toml
--8<-- "src/harness/builtin/configs/models/opus-5.5.toml"
```

</details>

<a id="experiments"></a>

## 实验

在 benchmark 上使用指定模型运行 agent：`configs/experiments/<name>.toml`，由 benchmark 包提供（eval 包运行它们）。应用的对话是按 `configs/assistant.toml` 修改后的 agent。

| 文件 | 说明 |
| --- | --- |
| `assistant` | 本机上的应用助手 |

<details>
<summary><code>configs/assistant.toml</code></summary>

```toml
--8<-- "src/harness/builtin/configs/assistant.toml"
```

</details>

<a id="deploys"></a>

## Deploy 文件

服务在某台机器上的运行位置：`configs/deploy/<machine>.toml`。

| 文件 | 说明 |
| --- | --- |
| `example-api` | 没有供模型使用的 GPU：仅模拟器在本机运行，所有模型均托管（main 和 vlm 角色）。没有分割器时，分割及其上层工具（locate、pick、release 等）被移除；没有策略服务器时，学习型 skill 也被移除，形成更小的配置和不同的 identity。 |

<details>
<summary><code>configs/deploy/example-api.toml</code></summary>

```toml
--8<-- "src/harness/builtin/configs/deploy/example-api.toml"
```

</details>

<a id="worker-options"></a>

## Worker 选项

`harness serve --options` 的选项（手动启动的 worker）。

| 文件 | 说明 |
| --- | --- |

