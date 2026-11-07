---
title: "learning"
---

提出笔记、记忆、技能和规则。可执行提案等待可信宿主验证其精确修订。ClosedLoop 用于定义有界执行的技能。兼容的练习环境可提供 sandbox。

- **层**: base（可选：仅在配置启用时提供）
- **所需服务**: –
- **依赖 skill**: –
- **冲突 skill**: –
- **永不移除**: 否
- **Mixin**: `skills.learning:Learning`
- **清单**: `skills/learning/skill.toml`

<a id="functions"></a>

## 函数

命名空间里还有：`library`、`ClosedLoop`、`sandbox`（skill 的 `exports(session)` 提供的常量和名字）。

<a id="what-the-model-reads"></a>

## 模型读到的内容

来自 RoboDojo prompt pack（`prompts/robodojo/`），启用所有 skill 和特性：

```text
    sandbox(op, **arguments) when the verifier provides a compatible environment.
```
