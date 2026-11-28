---
core: minor
external-agents: minor
agent: minor
app: minor
---
ACP agents now negotiate parameterized model options (`_meta.parameterizedModelPicker`) and expose all declared model configuration options—such as Effort, Context window, Fast mode, and Thinking—through a unified Cursor-style model menu in chat.
<!-- zh -->
ACP 协议全面打通参数化模型协商（`_meta.parameterizedModelPicker`）与通用模型配置项（`configOptions`），聊天底部统一模型菜单支持按模型能力动态选择思考强度、上下文窗口（如 256K / 500K）、Fast 开关等全部参数，并自动兼容迁移旧版 Cursor 括号模型配置。
