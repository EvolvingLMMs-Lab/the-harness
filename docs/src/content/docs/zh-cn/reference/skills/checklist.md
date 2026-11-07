---
title: "checklist"
---

在 agent 工作时向用户显示计划：任务步骤完成后逐项勾选。

- **层**: base（可选：仅在配置启用时提供）
- **所需服务**: –
- **依赖 skill**: –
- **冲突 skill**: –
- **永不移除**: 否
- **Mixin**: `skills.checklist:Checklist`
- **清单**: `skills/checklist/skill.toml`

<a id="functions"></a>

## 函数

### `plan`

```python
def plan(*steps)
```

向用户显示计划：按顺序给出简短的任务步骤，使用用户的语言，以字符串或一个列表传入。再次调用可修改计划；文字相同的已完成步骤保持勾选。返回步骤数。

### `step_done`

```python
def step_done(number)
```

勾选计划的第 `number` 步（1 表示第一步）。

<a id="what-the-model-reads"></a>

## 模型读到的内容

来自 RoboDojo prompt pack（`prompts/robodojo/`），启用所有 skill 和特性（额外启用 checklist）：

```text
  plan whenever what you see differs from what you expected.
```
