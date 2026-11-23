guide("chat-patterns"): matching incoming text with regular expressions; waiting for a line.

Patterns are kept in a list. Each has an index, its place in the list, counted from 0.
With the default options the list starts with three built-in patterns, indexes 0, 1 and
2 (the two 'whisper' patterns and the 'chat' pattern of guide("chat-events")).

bot.chatPatterns
  The bot has no property of this name: reading it gives undefined. The list of patterns
  is held inside the chat module; code reaches it only through the calls below.

bot.addChatPattern(name, pattern, { repeat = true, parse = false } = {}) -> number
  pattern: a RegExp; anything else throws 'Pattern parameter should be of type RegExp'.
  Adds one pattern. Returns its index.
  Each time the text of a 'messagestr' matches (pattern.test(text)), the bot emits
  'chat:<name>' with one argument:
    parse false: [text], an array holding the matched line.
    parse true: [[group1, group2, ...]], the capture groups of the match.
  repeat false: the pattern is removed after its first event.

bot.addChatPatternSet(name, patterns, { repeat = true, parse = false } = {}) -> number
  patterns: an array of RegExp; any other element throws 'Pattern parameter should be of
  type RegExp'.
  The set waits for patterns[0]; the first line that matches it moves the set on to
  patterns[1], and so on. Lines that do not match the pattern the set is waiting for
  leave it where it is. One line advances the set by one step at most.
  When the last pattern has matched, the bot emits 'chat:<name>' with one argument:
    parse false: [line0, line1, ...], the matched lines in order.
    parse true: [[groups of line0], [groups of line1], ...].
  Then, with repeat true the set starts again at patterns[0]; with repeat false it is
  removed.
  Returns the set's index plus 1.

bot.removeChatPattern(name)
  name a number: removes the pattern at that index.
  name a string: removes every pattern with that name ('chat' and 'whisper' are the
  names of the built-in ones).

bot.chatAddPattern(pattern, chatType) -> number
  The old form. Adds a pattern that emits the event named chatType itself (no 'chat:'
  prefix) on every match, with the arguments
  (group1, group2, ..., jsonMsg.translate, jsonMsg). Returns its index.

How one line is processed.
  On each 'messagestr' the bot collects every pattern or set whose awaited RegExp
  matches the text, then handles them in index order. When it reaches a set that has
  matched but is not complete yet, it stops: patterns with a higher index that matched
  the same line get no event for that line.

bot.awaitMessage(...matchers, timeout = 20000) -> Promise<string>
  matchers: strings, RegExps, or arrays of them, in any number. A last argument that is
  a number is the time limit in milliseconds.
  Resolves with the text of the first 'messagestr' that equals one of the strings
  exactly or matches one of the RegExps.
  Rejects with 'Timeout waiting for message after <timeout>ms' when none arrives within
  the time limit.
