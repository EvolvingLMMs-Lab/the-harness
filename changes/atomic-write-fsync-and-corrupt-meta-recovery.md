---
core: patch
agent: patch
---
Flush and fsync temporary files in `atomic_write` before `os.replace` so sudden reboots or power loss do not leave zero-filled JSON files, and gracefully recover corrupted `meta.json` and `origin.json` metadata so one damaged file never breaks the conversation list or skills listing.
<!-- zh -->
在 `atomic_write` 执行 `os.replace` 前先 `flush` 并 `os.fsync`，避免突然断电或重启导致 NTFS 留下全零损坏的 JSON 文件；同时为损坏的 `meta.json` 和 `origin.json` 增加优雅降级恢复，避免单个异常文件导致整个对话列表或技能列表无法加载。
