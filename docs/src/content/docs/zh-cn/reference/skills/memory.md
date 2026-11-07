---
title: "memory"
---

记忆，一套接口管两种：这一局看到了什么、在哪里（remember、recall、forget；由 host 保存，和子 agent 共用），以及 library 的记忆条目（recall；remember(..., keep=True) 将同一条目持久保存）。

- **层**: base
- **所需服务**: –
- **依赖 skill**: –
- **冲突 skill**: –
- **永不移除**: 是
- **Mixin**: `skills.memory:Memory`
- **清单**: `skills/memory/skill.toml`

<a id="functions"></a>

## 函数

### `remember`

```python
def remember(kind, text='', where=None, name=None, confidence=0.5, keep=False)
```

记住一条观察或笔记。keep=True 在可写的库中保存同一条目并沿用其 ID。

### `recall`

```python
def recall(query=None, k=5, kind=None, near=None, radius=None)
```

这一局的记忆和 library 的记忆条目，最好的在前：`kind` 的（一个名字，或一个家族："ore" 找到 "ore:iron"），离 `near` 最近的在前（默认：worker 告知时为你所在的位置；带 "distance"），在 `radius` 之内；否则按 `query` 最匹配（带 "score"）；否则这一局最新的在前。没有位置的条目排在有位置的条目之后，指定 `radius` 时只返回有位置的条目。每个条目 {"id", "scope": "run" 或 "library", "kind", "name", "text", "where", "evidence", ...}。

### `forget`

```python
def forget(ident)
```

按 ID 遗忘可见的条目。已持久保存的条目需要库的写权限。

<a id="what-the-model-reads"></a>

## 模型读到的内容

来自 RoboDojo prompt pack（`prompts/robodojo/`），启用所有 skill 和特性：

```text
  recall(query=None, kind=None, near=None): this run's notes and what earlier runs kept;
  forget(id) drops a note of this run.
```
