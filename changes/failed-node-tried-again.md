---
core: patch
---
A reflex node with `over` that failed is tried again when its situation comes anew, also where its condition and its `over` never hold at the same time (hungry below one level, fed above another). It stayed failed for good: its `over` was asked only while its condition held.
<!-- zh -->
带 `over` 的反射节点失败后，情况重新出现时会再次尝试，包括条件和 `over` 永远不会同时成立的节点（低于某个值算饿、高于另一个值算饱）。以前它会永远停在失败状态：只有条件成立时才会检查它的 `over`。
