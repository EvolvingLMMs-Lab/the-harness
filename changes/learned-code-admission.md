---
core: minor
---
A learning run can keep the skills and reactive rules the agent writes itself. The new setting `learning.admission` (`HARNESS_LEARNING_ADMISSION` wins over it) says how such code is admitted: `fixture` (the default, as before: only a fixture this computer provides for the entry), `own_test` (where the environment reports `physical: false`, the host also runs the entry's own test between programs; a pass admits it as provisional, shown as `provisional (own test)`, and later runs of the library load it), or `off` (no learned code is admitted or loaded). An entry admitted by its own test goes back to pending once 3 uses of it are recorded and fewer than a quarter succeeded. `harness library show` says for each code entry whether a fixture or its own test admitted it.
<!-- zh -->
学习运行现在可以留下 agent 自己写的 skill 和反应规则。新设置 `learning.admission`（`HARNESS_LEARNING_ADMISSION` 优先于它）决定这类代码如何被接纳：`fixture`（默认，与之前相同：只靠这台电脑为该条目提供的 fixture）、`own_test`（环境报告 `physical: false` 时，宿主还会在两个程序之间运行条目自带的测试；通过则以 provisional 接纳，显示为 `provisional (own test)`，该 library 之后的运行会加载它）或 `off`（不接纳也不加载任何学到的代码）。靠自带测试接纳的条目，记录满 3 次使用且成功不足四分之一时退回待验证。`harness library show` 会为每个代码条目标明它是由 fixture 还是自带测试接纳的。
