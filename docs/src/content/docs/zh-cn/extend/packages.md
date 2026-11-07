---
title: "编写包"
description: "把 skill、环境、实验、服务或 Agent Skills 打包成一个别人可以安装的包。"
---

**包**是一个包含 `package.toml` 的文件夹。The Harness 在核心之外能做的一切都以包的形式提供：环境及其
worker、skill 及其 prompt、反应规则、实验、模型服务、Agent Skills、设置，甚至 CLI 命令。你可以从 registry、git
仓库、压缩包或文件夹安装包（[包](/docs/zh-cn/configure/packages/)）。

## package.toml

```toml
[package]
name = "mine"
version = "0.1.0"
summary = "Save and export documents in the editors this team uses"
harness = ">=1.0,<2"              # the versions of The Harness it works with
depends = { computer = "^1.0" }   # other packages, by name and range
platforms = ["windows", "macos", "linux"]
license = "MIT"
homepage = "https://github.com/you/mine"

[provides]
commands = { mine-report = "mine.report:main" }   # adds `harness mine-report`
```

| 键 | |
|---|---|
| `name` | 小写字母、数字和连字符 |
| `version` | `MAJOR.MINOR.PATCH`；已发布的版本永不改变 |
| `summary` | 一行：它让 agent 能做什么 |
| `harness` | 它适用的 The Harness 版本范围（默认：任意） |
| `depends` | 它需要的其他包，按名字和版本范围 |
| `platforms` | `windows`、`macos`、`linux`（默认：全部） |
| `homepage`、`license` | 给人看的信息 |

## 工作区提供者

在 `package.toml` 中注册 host 模块：

```toml
[provides]
host = "my_package.host"
```

模块的 `Workspaces(directory, settings)` 实现 `harness.sdk.WorkspaceProvider`。
`kinds` 声明名称，`accepts` 按绑定输入选择提供者，`kind` 选择包自己的默认值。
`bind` 验证输入并返回 worker 选项与元数据，也负责从父会话继承绑定。
`bench`、`tree`、`builtin_skills`、`extra_skills` 提供环境配置；
`acquire`、`of`、`release`、`close` 管理资源。managed 执行和展示是可选能力。

核心发现所有已安装的提供者，拒绝重复名称并分派调用；不启动 native 进程，也不回退安装 computer。
先安装所需包；默认值不唯一时用 `--workspace KIND` 明确选择。后端设置放在包的 `settings.toml`。
通用租约计数使用 `WorkerPool`；浏览器传输、项目目录与进程清理留在各包。
与环境无关的 skill 可声明 `embodiments = ["*"]`，解析为已安装的本体种类；
新增环境无需修改核心 skill 的白名单。

## 它提供什么

其余一切都按它在文件夹中的位置识别：

```text
mine/
├── package.toml
├── README.md                  shown on the package's page
├── CHANGELOG.md
├── skills/<name>/             skills: skill.toml, __init__.py, prompt.md
├── agent-skills/<name>/       Agent Skills: SKILL.md and its files
├── embodiments/<name>/        environments the agent can act in: embodiment.toml
├── benches/<name>/            tasks and their worker: bench.toml
├── services/<name>.toml       model services
├── experiments/<name>.toml    experiments: harness run <name>
├── profiles/<name>.toml       agent configurations
├── prompts/                   prompt text for its environments
├── settings.toml              sections of the app's settings
├── config_keys.toml           configuration keys it reads, with what each does
└── tests/                     its tests
```

`[provides]` 也可以列出这些文件夹中所含内容的名字，用来说明这个包的用途。registry
会为这一切建立索引，一次运行正是靠它找到能提供所缺环境、skill 或服务的包。

## 自己的页面

有页面的包在 `package.toml` 里写明一个 host 模块，session host 会在 app 旁边提供这个模块声明的内容：

```toml
[provides]
host = "harness_mine.host"
```

```python
# harness_mine/host.py
pages = {"/mine": "mine.html"}    # ui/static/mine.html at /mine
```

页面的其他文件在 `/static/mine/<文件>`（包的 `ui/static/<文件>`，含子文件夹）。`/` 仍然是 app 的页面；没装 app
时，是第一个声明了 `/` 的包的页面。打开页面时地址里带着会话密钥（`?token=...`），服务器把它存进 cookie，供页面之后的请求使用。

同一个模块还可以给页面提供自己的 API，挂在 `/api/<包名>/<名字>`：

```python
def inbox(server, data):          # data: a GET's query, a POST's JSON body
    return {"topics": []}         # answered as JSON

api = {"inbox": inbox}            # GET or POST /api/mine/inbox
```

这些接口和 session host 的其他接口用同一个会话密钥校验；抛出 `ValueError` 或 `KeyError` 时返回 400 和它的文字。核心自己的接口优先。

前端还可以用自己的 profile 启动 assistant 的对话：只有这些对话才有的 skill，以及加进系统提示的文字。

```python
profiles = {"mine": Path(__file__).parent.parent / "profiles" / "mine.toml"}
```

```toml
# profiles/mine.toml
description = "Conversations the mine page starts"
skills = ["report"]        # optional skills of the package; off in every other conversation
prompt = "../prompts/mine.md"
```

`POST /api/app/conversations {text, profile: "mine"}` 启动一个这样的对话；不带 profile 启动的对话既没有这些 skill，也没有这段提示。

## SDK

包的 Python 代码只导入 `harness.sdk`、标准库、它自己的模块、它依赖的包，以及它声明的第三方模块。`harness.sdk`
是面向包的稳定接口：会话和 skill、事件和 trace、`ClosedLoop` 类、embodiment 和 bench、服务客户端、设置和路径。它的不兼容变更只会随
The Harness 的新主版本出现，所以写明 `harness = ">=1.0,<2"` 的包在整个 1.x 中都能继续工作。

## 开发

```bash
harness install ./mine --link    # use the folder in place: edits apply to the next run
harness list mine                # what The Harness found in it
```

在 `tests/` 中按核心测试的写法编写测试：发布之前，它们会在一个干净的主目录中、装好这个包的情况下运行。

## 发布

- **通过 git**：把文件夹推送到一个仓库，并分享来源，
  `git:github.com/you/repo@v0.1.0#mine`。任何人在确认它提供的内容后都可以用 `harness install` 安装它。
- **作为压缩包**：把文件夹打成 `.tar.gz`，放在一个 https 地址上。
- **放进 registry**：registry 是一个文件夹，包含一个 `index.json` 和每个版本一个压缩包，通过 https 提供，或通过
  `HARNESS_REGISTRY` 在本地使用。官方 registry 列出随 The Harness 一起维护的包；要提议加入一个包，在它的仓库中提一个 issue。

[包目录](https://harness.lmms-lab.com/packages/)显示每个官方包的 README，所以请为安装这个包的人来写它：它做什么、它在
Python 之外需要什么、如何使用、它的设置和它的局限。
