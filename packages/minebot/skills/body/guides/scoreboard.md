guide("scoreboard"): scoreboard objectives, their scores, their events.

bot.scoreboards              object: objective name -> ScoreBoard
bot.scoreboard               object: display position number -> ScoreBoard, with three
                             named readers:
                               bot.scoreboard.list        position 0
                               bot.scoreboard.sidebar     position 1
                               bot.scoreboard.belowName   position 2
                             A position that shows nothing is undefined

ScoreBoard fields.
sb.name                      the objective's name (string)
sb.title                     the display text. The text of the packet is parsed as JSON
                             and its 'text' field is taken (undefined when the component
                             has none); text that is not JSON is kept as it is
sb.itemsMap                  object: entry name -> item
sb.items                     array of the items, highest value first
item.name                    the entry's name: a player's username or any string
item.value                   the score (integer)
item.displayName             ChatMessage. For a name that is in bot.teamMap: that team's
                             displayName(name). Otherwise the name itself

ScoreBoard methods (they change the object only).
sb.add(name, value) -> item      sets or replaces the entry
sb.remove(name) -> item          deletes the entry; returns it, or undefined
sb.setTitle(text)                sets sb.title by the rule above

Events.
'scoreboardCreated' (scoreboard)
  The server creates an objective. A new ScoreBoard, with no items, is stored under its
  name.
'scoreboardDeleted' (scoreboard)
  The server removes an objective. Emitted before the entry is deleted from
  bot.scoreboards; the argument is undefined for a name that was not stored. After the
  event the first position of bot.scoreboard that shows a scoreboard of that name is
  cleared.
'scoreboardTitleChanged' (scoreboard)
  The server changes an objective's display text. For a name that is not in
  bot.scoreboards the bot emits 'error' with the message
  'Received update for unknown objective NAME' and no title event.
'scoreUpdated' (scoreboard, item)
  The server sets a score in a stored objective. item is the new { name, value,
  displayName }. A score for an objective that is not stored is dropped.
'scoreRemoved' (scoreboard, item)
  The server removes a score. When the packet names a stored objective: the entry is
  removed there; item is the removed entry, or undefined when there was none. When it
  names no stored objective: the entry is removed from the first scoreboard that holds
  that name, and the event is emitted for that one; with no such scoreboard, nothing.
'scoreboardPosition' (position, scoreboard, previous)
  The server shows a stored objective at a position. position: the number in the packet.
  previous: the ScoreBoard that was at that position, or undefined. bot.scoreboard is
  updated after the event. A packet that names no stored objective does nothing: the
  position keeps what it had.
