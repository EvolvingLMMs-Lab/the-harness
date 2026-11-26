---
core: minor
agent: patch
computer: patch
workspace: patch
---
Every setting has a title, a description and a name for each of its choices in English and Chinese, including the computer package's (`computer.*`, `physical.rules`, `privacy.rules`) and `workspace.workers`. A setting's description says whether it is shown to a person at all (`shown`: false for the two `model.think_*` keys that no longer do anything and for `personal.*`, which only carry what an earlier version kept) and whether it is tuning few people need (`advanced`); a package's `settings.toml` gives `shown = false` and `advanced = true`. `harness config show` leaves out what is not shown (`--all` lists it).
<!-- zh -->
每个设置都有中英文的标题、说明和每个选项的名字，包括 computer 包的（`computer.*`、`physical.rules`、`privacy.rules`）和 `workspace.workers`。设置的描述里说明它要不要显示给人（`shown`：已经不起作用的两个 `model.think_*` 和只保存旧版本数据的 `personal.*` 为 false），以及它是不是少数人才需要的调节（`advanced`）；扩展包在 `settings.toml` 里写 `shown = false` 和 `advanced = true`。`harness config show` 不列出不显示的项（`--all` 才列）。
