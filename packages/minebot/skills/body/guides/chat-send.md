guide("chat-send"): sending chat, commands and whispers; asking the server to complete text.

bot.chat(message) -> undefined
  message: a string or a number. A number is turned into its string. Any other type throws
  'Chat message type must be a string or number: <typeof message>'.
  A message that starts with '/' is sent whole as one chat packet, whatever its length.
  Any other message is cut at each '\n'. Empty lines are dropped. Each line is cut into
  pieces of at most 256 characters, and each piece is sent as one chat packet, in order.
  The packets are written at once. The call does not wait for the server and reports
  nothing about what the server did with the text. The server's answer, and the bot's
  own line, arrive like any other message: guide("chat-events").

bot.whisper(username, message) -> undefined
  Sends '/tell <username> <message>'. message: a string or a number, as for bot.chat.
  The message is cut at each '\n', empty lines are dropped, and each line is cut into
  pieces of at most 256 - ('/tell ' + username + ' ').length characters. Every piece is
  sent as its own '/tell <username> <piece>' packet. A message that starts with '/' is
  cut the same way.

The length limit.
  256 is the default on 1.16.1. The option chatLengthLimit of createBot replaces it; it
  is read once, when the bot is created.

bot.tabComplete(text, assumeCommand = false, sendBlockInSight = true, timeout = 5000)
    -> Promise<[{ match, tooltip }]>
  Writes one tab_complete packet holding text, then waits for the next tab_complete
  packet from the server, whichever request it answers.
  Resolves with the list in that packet: match is the completed word (a string), tooltip
  is a string or undefined.
  Rejects with 'Event tab_complete did not fire within timeout of <timeout>ms' when no
  answer comes within timeout milliseconds. timeout 0 or less: no time limit.
  assumeCommand is not part of the 1.16.1 packet and changes nothing. With
  sendBlockInSight true the call runs bot.blockAtCursor() first; the result is not part
  of the 1.16.1 packet either.
