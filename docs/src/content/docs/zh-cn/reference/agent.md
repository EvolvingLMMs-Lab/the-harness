---
title: "Agent 配置"
description: "core 的默认配置与运行时绑定。"
---

core 默认配置声明控制参数。实际自然语言任务由所选 workspace provider 绑定目标环境、技能和提示词；可选 agent 包另外管理持续身份和多轮历史。

<details>
<summary>默认配置</summary>

```toml
--8<-- "src/harness/builtin/configs/default.toml"
```

</details>

控制程序的 Python 环境与目标 workspace 分开。具体接口见[Python API](/docs/zh-cn/extend/python-api/)。
