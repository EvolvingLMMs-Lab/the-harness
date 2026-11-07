---
title: "Python API"
sidebar:
  label: 概览
  order: 0
---

英文参考由 docstring 生成，中文版手动同步。多数用户只需 CLI 和配置文件；这些模块供进一步开发使用。

- [配置](/docs/zh-cn/reference/api/configuration/): `harness.config`, `harness.config.agent`, `harness_eval.experiments`
- [Episode 运行时](/docs/zh-cn/reference/api/episode-runtime/): `harness.runtime.messages`, `harness.runtime.kernel`, `harness.runtime.episode`, `harness.runtime.input`, `harness.runtime.shield`, `harness.runtime.control`
- [事件与反应层](/docs/zh-cn/reference/api/events-and-the-reactive-layer/): `harness.runtime.events`, `harness.runtime.reactive`
- [Tick 与条目](/docs/zh-cn/reference/api/tick-and-entries/): `harness.runtime.tick`, `harness.runtime.entries`
- [对话](/docs/zh-cn/reference/api/conversations/): `harness.runtime.chat`, `harness.runtime.conversation`, `harness.core.spans`
- [Skill 与提示词](/docs/zh-cn/reference/api/skills-and-prompts/): `harness.runtime.skills`, `harness.runtime.prompts`
- [Suite 与报告](/docs/zh-cn/reference/api/suites-and-reports/): `harness_eval.suite`
- [服务](/docs/zh-cn/reference/api/services/): `harness.services.registry`, `harness.services.placement`, `harness_local_models.deploy`, `harness_local_models.supervisor`, `harness.services.broker`
- [会话主机](/docs/zh-cn/reference/api/session-host/): `harness.host.http`, `harness.host.client`, `harness.core.episodes`, `harness.transcript`, `harness.terminal`, `harness.extensions`
- [机器人与 worker](/docs/zh-cn/reference/api/robots-and-workers/): `harness.core.remote`, `harness.core.worker`, `harness.embodiments`
