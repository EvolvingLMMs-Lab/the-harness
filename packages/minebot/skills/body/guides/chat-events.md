guide("chat-events"): the events emitted when text arrives from the server.

Every chat packet from the server carries a text component, a position (0, 1 or 2) and a
sender UUID. The component becomes a ChatMessage (guide("chat-message-object")). The
events below are emitted in this order for each packet.

'message' (jsonMsg, position, sender, verified)
  jsonMsg: the ChatMessage.
  position: 'chat' for packet position 0, 'system' for 1, 'game_info' for 2.
  sender: for position 0, the UUID string in the packet; for 1 and 2, null.
  verified: false for position 0; not passed (undefined) for 1 and 2.

'messagestr' (text, position, jsonMsg, sender, verified)
  text: jsonMsg.toString(), the plain text with colour codes removed. The other
  arguments are those of 'message'.

'actionBar' (jsonMsg, null)
  Emitted after the two events above, for packet position 2 only.

'chat' (username, message, translate, jsonMsg)
  Emitted when the text of a 'messagestr' matches the built-in chat pattern
  /^(?:\(.{1,15}\)|\[.{1,15}\]|.){0,5}?(\w+)\s?[>:\-»\]\)~]+\s(.*)$/
  whatever its position. The pattern accepts up to 5 leading characters or bracketed
  groups, then the name, then one or more of > : - » ] ) ~, then a space, then the text.
  '<Steve> hello' gives username 'Steve', message 'hello'. '[Admin] Bob: hi' gives 'Bob',
  'hi'. The server line '[Server] text' (the say command) gives 'Server', 'text'.
  username: the first capture group. message: the second.
  translate: jsonMsg.translate, the translation key of the component
  ('chat.type.text' for a player's chat line), or undefined when it has none.
  jsonMsg: the ChatMessage.
  The bot's own lines match too; username is then bot.username.

'whisper' (username, message, translate, jsonMsg)
  Emitted when the text matches one of two built-in patterns:
  /^(?:\(.{1,15}\)|\[.{1,15}\]|.){0,5}?(\w+) whispers(?: to you)?:? (.*)$/
  /^\[(?:\(.{1,15}\)|\[.{1,15}\]|.){0,5}?(\w+) -> \w+\s?\] (.*)$/
  'Steve whispers to you: psst' gives username 'Steve', message 'psst', translate
  'commands.message.display.incoming'. '[Steve -> me] psst' gives 'Steve', 'psst'; that
  text also matches the chat pattern, and 'chat' fires as well with username 'Steve',
  message 'me] psst'.

Order.
  For one packet: 'message', then 'messagestr'. The pattern events ('whisper', 'chat',
  and those added with bot.addChatPattern) are emitted inside 'messagestr', before
  'actionBar'.

Switching the built-in patterns off.
  The option defaultChatPatterns of createBot, default true. With false the three
  patterns are not installed and 'chat' and 'whisper' are not emitted.
  bot.removeChatPattern('chat') and bot.removeChatPattern('whisper') remove them later.
