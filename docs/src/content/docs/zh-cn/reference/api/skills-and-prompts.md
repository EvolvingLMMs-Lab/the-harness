---
title: "Skill 与提示词"
---

## `harness.runtime.skills`

Skill：模型所写程序调用的 API。

skill 是源码目录中的 `skills/<name>/` 包，包含：

    skill.toml      name, summary, layer, the names it exports, what it needs
    __init__.py     a mixin class with the methods (and optional exports(session) and
                    turn_report(session): what the skill adds to the model's next turn
                    after every program)

skill 在 `embodiments` 指定的本体类型上运行（默认 robot）。kernel session 类由本体 session（runtime/episode.py）与该本体所有 skill 的 mixin 组成，因此 skill 可相互调用方法。

程序可见的 skill 按每次运行决定：由系统或接口层指定；缺少服务或不支持当前本体的 skill 会同时从 kernel 命名空间和提示词（runtime/prompts.py）中移除，确保模型不读到无法调用的 API。

各包的 skill（每个包的 skills/，paths.roots：源码检出中的包和用户安装的包）与内置 skill 一起加载；校验失败或与内置 skill 冲突的条目会被排除（USER_PROBLEMS 说明原因），永不改变内置 skill。

### `Skill`

```python
class Skill
```

按 skill.toml 声明的 skill（SKILL_KEYS）；`path` 为其目录。

#### `for_embodiment`

```python
def for_embodiment(embodiment: str | None) -> 'Skill'
```

读取适用于该本体的 skill 接口。

#### `public`

```python
def public() -> tuple[str, ...]
```

不以下划线开头的导出名称，即向程序说明的 API（不包含对话的钩子 `__wrap_up__`）。

### `load_skills`

```python
def load_skills(root: Path=SKILLS_ROOT, user: bool=True) -> dict[str, Skill]
```

按提示词顺序返回 `root` 下所有 skill；对于内置 skill，还包括各包的 skill（每个包的 skills/ 目录，paths.roots），除非 `user` 为 false。

### `skills_for_layers`

```python
def skills_for_layers(layers: dict | None, root: Path=SKILLS_ROOT, *, embodiment: str='robot') -> list[str]
```

按开关指定接口层（{"learned": bool, ...}，覆盖 LAYER_DEFAULTS），返回适用于本体类型的 skill，不含可选 skill。

### `probes`

```python
def probes(root: Path=SKILLS_ROOT) -> list[str]
```

为某个本体做 probe 的 skill（带 [probe] 表的 skill），每种本体类型一个或多个。

### `available_services`

```python
def available_services(options: dict) -> set[str]
```

kernel 选项提供的服务类型：分割器、pointer、VLM 和验证器配置，以及至少一个策略、世界模型或 MCP 服务器。

### `Resolution`

```python
class Resolution
```

`resolve` 的结果：按提示词顺序排列的已启用 skill，以及每个被移除的 skill 和原因。

#### `to_dict`

```python
def to_dict() -> dict
```

将解析结果转为普通字典。

### `resolve`

```python
def resolve(requested, services: set[str], *, strict: bool=False, root: Path=SKILLS_ROOT, embodiment: str='robot') -> Resolution
```

从请求的 skill 中选出适用于当前本体、且所需服务可用的 skill。不支持本体、缺少所需服务或依赖 skill 未启用时移除（重复直到不再变化）；本体必需的 skill 始终启用。启用 strict 后，任何 skill 被移除都会报错，避免评测时实际运行的系统少于声明的功能。

### `mixins`

```python
def mixins(root: Path=SKILLS_ROOT, *, embodiment: str='robot', knowledge: str='handwritten') -> list[type]
```

导入本体类型对应的所有 skill 的 mixin 类，并按 skill 顺序返回（即 session 的方法解析顺序）；knowledge 为 "learned" 时不含手写的那些（它们的模块不导入）。

### `handwritten`

```python
def handwritten(root: Path=SKILLS_ROOT) -> list[str]
```

为某个游戏手写的知识所在的 skill。

### `namespace`

```python
def namespace(session, names, root: Path=SKILLS_ROOT) -> dict
```

启用 skill `names` 的 session 的 kernel 命名空间：若模块定义 exports(session)，则使用其返回值；否则使用 session 上该 skill 导出的属性。

### `reporters`

```python
def reporters(names, root: Path=SKILLS_ROOT) -> list
```

按 skill 顺序返回 `names` 的轮次报告：各模块的 turn_report(session) -&gt; {"text", "images"} 或 None，session 在每个程序结束后调用（EpisodeCore.drain）。

### `exported_names`

```python
def exported_names(root: Path=SKILLS_ROOT) -> dict[str, tuple[str, ...]]
```

每个导出名称及导出它的 skill（仅互相冲突的 skill 可导出同名项）。

## `harness.runtime.prompts`

根据运行启用的 skill，从 prompt pack 组装系统提示词。

pack 是包含 Markdown 区段的目录（prompts/robodojo、prompts/robotwin）。pack.toml 按顺序列出区段；带 `skills` 的区段仅在其中某个 skill 启用时包含：

    sections = [
      { file = "core.md" },
      { file = "learned.md", skills = ["vla", "wam"] },
      { file = "rules_learned.md", skills = ["vla"], optional = true },
    ]

区段 { installed = true } 是用户安装（应用）且已启用的 skill：每个 Harness skill 的摘要、调用和 prompt.md，以及每个 Agent Skill 的名称和描述（runtime.installed_skills、runtime.agent_skills）。

区段内可仅为特定 skill 保留部分行：

    &lt;!-- if: pointing, segmentation --&gt;      kept when all named skills are enabled
    ...
    &lt;!-- else --&gt;                            kept otherwise (optional)
    ...
    &lt;!-- end --&gt;

标记还可指定连接的特性（FEATURES）：measured_gripper 表示夹爪读数为实测开度，而非只报告上次命令的契约；step_limit 表示会报告 episode 步数上限（core/contract.py）；channels 表示 benchmark 的本体声明了通道（游戏的键、鼠标和滚轮分组，由单元占用：runtime/tick.py）。think_while_acting 永不成立（模型的这一轮现在始终属于它自己）：pack 里为它写的文本会被略去。标记行不会传给模型，因此全部 skill 和特性启用时，提示词就是去掉标记的 pack 文本。API 文档留在 pack 中，因为它描述具体本体的坐标系、可达范围和数值；skill 代码对所有本体相同。

### `features_for`

```python
def features_for(runtime: dict, channels: bool=False, *, embodiment=None) -> set[str]
```

运行时配置（观测契约）对应的提示词特性；本体声明了通道时还有 `channels`。

### `pack`

```python
def pack(directory: Path) -> dict
```

pack 设置：区段和未提供文档的导出名称。

### `sections`

```python
def sections(directory: Path) -> list[dict]
```

按顺序返回 pack 区段（{"file"，以及可选的 "skills"、"optional"}）：来自 pack.toml，缺失则使用 DEFAULT_SECTIONS。

### `select`

```python
def select(text: str, skills) -> str
```

根据已启用的 `skills`，保留 `text` 中 if/else 标记条件成立的行。

### `marked_skills`

```python
def marked_skills(text: str) -> set[str]
```

`text` 标记中引用的 skill。

### `installed_section`

```python
def installed_section(skills, installed=(), agent_skills=None, *, embodiment=None) -> str
```

installed 区段：用户安装的 Harness skill（`installed`，名称）中已启用的，每个附摘要、调用和 prompt.md；然后是 Agent Skills（{name: {"description", "path"}}），每个给出名称和描述。

### `assemble_prompt`

```python
def assemble_prompt(directory: Path, skills, overrides: dict | None=None, features=('measured_gripper',), installed=(), agent_skills=None, *, embodiment=None) -> str
```

将适用于已启用 `skills` 和连接 `features` 的 pack 区段拼接。`overrides` 将区段名（不含后缀的文件名）映射到其他文件，例如另一种本体的 core 区段；`installed` 和 `agent_skills` 填充 installed 区段（installed_section）。

### `mentions`

```python
def mentions(text: str, name: str) -> bool
```

提示词是否引用某个 API 名称：函数和对象按调用或属性访问检查（`recall(`、`library.propose(`），常量（大写）和类（ClosedLoop）按单词检查。

### `documentation_gaps`

```python
def documentation_gaps(directory: Path, skills, exported: dict, features=('measured_gripper',)) -> dict
```

组装后提示词中的 API 错误：`missing` 为已启用 skill 中从未展示调用的函数（pack 明确列为无文档者除外）；`stray` 为仍被提到的已禁用 skill 名称。`exported` 将每个导出名称映射到导出它的一个或多个 skill。
