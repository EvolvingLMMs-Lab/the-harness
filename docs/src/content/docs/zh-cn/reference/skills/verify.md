---
title: "verify"
---

可在程序中调用的成功验证器（系统未配置时返回 None）。

- **层**: base
- **所需服务**: –
- **依赖 skill**: –
- **冲突 skill**: –
- **永不移除**: 是
- **Mixin**: `skills.verify:Verify`
- **清单**: `skills/verify/skill.toml`

<a id="functions"></a>

## 函数

### `verify`

```python
def verify(claim, cameras=None)
```

询问成功验证器，当前相机视图中 `claim` 是否成立。返回 (holds, answer)：肯定时 holds 为 True，否定时为 False，此配置禁用验证器时为 None。

<a id="what-the-model-reads"></a>

## 模型读到的内容

来自 RoboDojo prompt pack（`prompts/robodojo/`），启用所有 skill 和特性：

```text
  verify(claim, cameras=None) -> (holds, answer)   asks the success verifier about the
      current camera views; holds is True, False, or None when there is no verifier
```
