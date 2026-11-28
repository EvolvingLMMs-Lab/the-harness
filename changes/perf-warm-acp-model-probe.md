---
core: patch
app: patch
---
Reuse one warm ACP probe session per provider (serialized with idle eviction) and switch catalog models immediately with background metadata hydration, cutting ACP model switching latency from ~5-10s (cold process spawns) to ~100ms.
<!-- zh -->
按 ACP 提供方复用单个长驻探测会话（串行互斥 + 闲置自动回收）并实现目录模型瞬切与后台无感补齐参数，彻底消除切模型时反复冷启动多个 `node.exe` 进程造成的 5~10 秒卡顿，将切换耗时降至毫秒级。
