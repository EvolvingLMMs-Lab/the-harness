---
core: patch
---
Invalid configuration files now report their path and error without being overwritten. Model setup recovers after you supply a missing key, uses the enabled model's provider for readiness checks, reports conflicting default model choices, respects OpenRouter endpoint overrides, and reuses existing credentials; Custom endpoints can run without a key.
Continuations reject options for new conversations instead of silently ignoring them. Command options must follow their command, and an effort that could not be applied during model recovery is reported. Terminal startup also rejects model/effort flags combined with an external agent.

<!-- zh -->
配置文件有误时会显示路径和原因，不再覆盖原内容。补齐缺失的密钥后可以继续配置模型；就绪检查使用实际启用的模型，默认模型冲突会明确报错，OpenRouter 使用你指定的端点，并复用已有凭据。自定义端点支持不需要密钥的本地服务。
续接时会拒绝用于新对话的选项，不再默默忽略。选项须写在命令之后；模型恢复期间无法应用的推理强度会明确提示。启动终端时，模型或推理强度参数也不能与外部 agent 参数合用。
