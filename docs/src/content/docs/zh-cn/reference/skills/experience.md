---
title: "experience"
---

库里练习得到的经验：每个 skill 的表现（次数、成功率、用时、常见失败原因），以及 skill 记下的有效做法（hint、keep_hint），只作"先试"，总要核实。

- **层**: base（可选：仅在配置启用时提供）
- **所需服务**: –
- **依赖 skill**: –
- **冲突 skill**: –
- **永不移除**: 否
- **Mixin**: `skills.experience:Experience`
- **清单**: `skills/experience/skill.toml`

<a id="functions"></a>

## 函数

### `hint`

```python
def hint(kind, key)
```

练习中记下的、对 (kind, key) 有效的做法，没有则为 None：只是先试的东西，不是事实；要核实它给的结果，不成立就退回常规做法。

### `keep_hint`

```python
def keep_hint(kind, key, value)
```

把 value 记为有效做法，None 表示忘掉。它和普通记忆使用同一条存取路径，可写的运行可以将它保存在库中。

### `experience`

```python
def experience(skill=None)
```

读取实际启用版本的练习统计。旧结果如果只有技能名，显示为历史版本未知。

<a id="what-the-model-reads"></a>

## 模型读到的内容

来自 RoboDojo prompt pack（`prompts/robodojo/`），启用所有 skill 和特性，再加上 experience：

```text
  hint(kind, key)                   what a skill noted as working before for (kind, key),
                                    or None: only something to try first, never a fact
  keep_hint(kind, key, value)       note a small JSON value that worked (None forgets it)
  experience(skill=None)            how each skill did in practice so far: {skill: {"runs",
                                    "ok", "rate", "seconds" (mean), "failures": {reason:
                                    n}}}, or one skill's entry (None if never run). Plan
                                    around skills that often fail; their common failure is
                                    what to guard against
```
