---
title: "environments"
---

选定的环境做不了某一步时，在对话中取用另一个环境；并可请用户打开子 agent。

- **层**: base（可选：仅在配置启用时提供；会话主机为用户发起的对话启用）
- **所需服务**: –
- **依赖 skill**: –
- **冲突 skill**: –
- **永不移除**: 否
- **Mixin**: `skills.environments:Environments`
- **清单**: `skills/environments/skill.toml`

<a id="functions"></a>

## 函数

### `use_environment`

```python
def use_environment(kind, why, folder=None)
```

在这个对话中取用另一个环境：`kind` 是已安装的一种（"project"、"browser"、"desktop"、"apps"、"display"），`why` 是询问用户时给他看的一句理由。取用项目需要 `folder`。返回该环境，之后它的调用写作 `kind.call(...)`（`desktop.click`、`project.run_command`、`browser.read_page`）；用户或其设置拒绝时抛出带原因的 ValueError。用户先暂停时返回 None。

是否询问由设置 `environments.attach` 及其规则决定；无论是否询问，每次取用及理由都会显示并写入 trace。

### `release_environment`

```python
def release_environment(kind)
```

归还用 `use_environment` 取用的环境。原先已取用时返回 True。

### `request_agents`

```python
def request_agents(why)
```

请用户为这个对话打开子 agent（`why`：给用户看的一句理由）。打开后返回 True（此后 `delegate`、`wait_agents`、`send_agent`、`cancel_agent` 可用）；被拒绝时抛出带原因的 ValueError。
