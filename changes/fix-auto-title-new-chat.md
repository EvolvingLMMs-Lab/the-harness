---
agent: patch
app: patch
---
Fix automatic first-turn conversation naming for UI-created chats by recognizing localized default titles (`New conversation`, `新对话`) and passing `title_source: "default"` on new chat creation.
<!-- zh -->
修复从界面新建的对话无法自动生成首轮标题的问题：将多语言默认占位标题（`New conversation`、`新对话`）统一识别为默认标题，并在新建对话请求中显式传入 `title_source: "default"`。
