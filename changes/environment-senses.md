---
core: minor
---
An environment that can run code where it is offers senses: `sense(name, code)` has it compute a value in its own language each time it reports its state, and conditions of rules and trees read it as `view["sensed"][name]`, programs as `get_state()["sensed"][name]`. What a condition could not see in the reported state is defined once and serves the reactive layer and programs alike. A worker offers it with `"senses": True` in its profile and the methods `sense`, `senses` and `drop_sense`.
<!-- zh -->
能在自己那边运行代码的环境提供感知量：`sense(name, code)` 让环境每次报告状态时用它自己的语言算出一个值，规则和树的条件用 `view["sensed"][name]` 读它，程序用 `get_state()["sensed"][name]` 读它。条件原先在状态里看不到的东西只需定义一次，反应层和程序共用。worker 在 profile 里声明 `"senses": True` 并提供 `sense`、`senses`、`drop_sense` 即可。
