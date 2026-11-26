---
agent: minor
---
A calendar entry put at a time that has already passed (added there, or moved there) is on the calendar as missed and wakes nothing; before, it came due at once and the model was called for it. Of a repeating entry, the times before it was put there are missed and its next time comes due as usual. The calendar can be searched: `harness calendar -q TEXT`, `Agent.calendar(q=...)`, `GET /api/agent/calendar?q=`.
<!-- zh -->
放在已经过去的时间上的日历条目（建在那里，或者拖到那里）在日历上记为“错过”，不会叫醒任何东西；以前它会立刻被当成到期而调用模型。重复的条目，放上去之前的那些时间记为错过，下一次照常到期。日历可以搜索：`harness calendar -q 文字`、`Agent.calendar(q=...)`、`GET /api/agent/calendar?q=`。
