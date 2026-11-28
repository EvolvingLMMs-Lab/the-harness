---
core: patch
external-agents: patch
---
ACP model backends now cancel stray built-in tool calls and retry with explicit corrective guidance instead of failing immediately or repeating the same prompt blindly, and prefer read-only `ask` mode over `default`.
<!-- zh -->
ACP 模型后端在模型误触发原生工具调用时，会立即取消并在新会话中附带明确纠错提示重试，不再直接失败或无反馈盲重试；同时在会话模式选择中优先使用只读的 `ask` 模式而非 `default`。
