---
title: "instructions"
---

读取用户在应用中安装的 skill 的说明和文件（Agent Skills，即包含 SKILL.md 的目录）。

- **层**: base（可选：仅在配置启用时提供）
- **所需服务**: –
- **依赖 skill**: –
- **冲突 skill**: –
- **永不移除**: 否
- **Mixin**: `skills.instructions:AgentSkills`
- **清单**: `skills/instructions/skill.toml`

<a id="functions"></a>

## 函数

### `read_skill`

```python
def read_skill(name, file='SKILL.md')
```

已安装 skill `name` 的说明（SKILL.md），或按 skill 内相对路径读取其他文件（"reference.md"、"scripts/fill.py"）。文件不存在时，ValueError 会列出该 skill 的文件。
