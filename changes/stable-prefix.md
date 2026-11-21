---
core: minor
---
The system prompt stays as the conversation began: a library entry that comes into force, or a skill or an environment that joins or leaves, is told as a note with the model's next call. After a summary of the conversation the pages read are named in one line, not given again whole; the model reads one again with `guide(name)`. Both keep what the model has read the prefix its provider caches, and what stands after a summary small.
<!-- zh -->
系统提示词保持对话开始时的样子：库条目生效、技能或环境加入或离开时，改为在模型下一次调用时以一条消息告知。对话被摘要后，读过的页面只列名字，不再整页附上，要再读用 `guide(name)`。这两点都让模型读过的内容保持为服务商可缓存的前缀，也让摘要之后剩下的上下文更小。
