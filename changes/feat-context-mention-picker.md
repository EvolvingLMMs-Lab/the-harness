---
agent: patch
app: patch
---

Replace the flat file-only `@` popup with an Antigravity-style structured Context Mention Picker (`Browse`: Rules, Conversation, Memory, Artifacts, Files; `Plugins & Skills`: skills, connected places, Customizations) supporting two-level drill-down (`@rule:`, `@chat:`, `@memory:`, `@artifact:`, `@file:`, `@skill:`) and cross-category search, backed by real server-side mention resolution (`Life.resolve_mentions` + `Session._with_files`) that injects referenced context safely into model requests without mutating saved user messages.
