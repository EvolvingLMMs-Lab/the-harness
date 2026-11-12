---
core: minor
---
An environment's own events can reach the model at once. A session that sets `watch_seconds` is read that often for the events it reports by itself (`observation_event_kinds`) also while no program acts and no rule is on time; an event whose detail says `"needs_model": True` is told to the model when no handler takes it (a wait ends, a call in flight is asked again); and `_event_views(event)` lets the environment give pictures with an event, which the model gets beside the event's text. Environments that set none of these behave as before.
<!-- zh -->
环境自己的事件可以立刻送到模型。设置了 `watch_seconds` 的 session，即使没有程序在行动、也没有按时间判断的规则，也会按这个间隔被读取，以取得它自己报告的事件（`observation_event_kinds`）；detail 里写着 `"needs_model": True` 的事件，在没有 handler 处理时会告诉模型（等待结束，在途的调用重新询问）；`_event_views(event)` 让环境给事件附上图片，模型会在事件的文字旁边收到它们。这些都没有设置的环境，行为与之前相同。
