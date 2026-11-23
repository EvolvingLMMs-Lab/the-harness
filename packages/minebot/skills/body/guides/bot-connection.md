guide("bot-connection"): the bot object's version fields, bot.supportFeature, the events of
the connection, bot.end, bot.quit, being kicked.

Fields set when the protocol client knows the game version (before 'inject_allowed').
  bot.version           '1.16.1': the game version string
  bot.majorVersion      '1.16'
  bot.protocolVersion   736
  bot.registry          the data of that version (blocks, items, entities, effects ...,
                        by id and by name), the same object the plugins use
  bot.supportFeature(name) -> value
    The value of a named feature for this version: true or false for most names, a
    number or string for a few (for example 'metadataIxOfItem' gives 7). A name that
    does not exist gives false.
  bot._client           the protocol client. bot._client.write(name, params) sends a
                        packet; bot._client.on(name, fn) listens to a packet.
  bot.username          set at the login packet: the name the client logged in with
  bot._warn(...message) prints '[mineflayer]' and the message with console.warn; prints
                        nothing with the createBot option hideErrors true

Events, in the order of a session.
  'connect' ()            the socket is connected
  'inject_allowed' ()     the plugins are loaded: guide("bot-plugins")
  'login' ()              the login packet arrived: guide("game-state")
  'spawn' ()              first health packet with health above 0: guide("health")
  'kicked' (reason, loggedIn)
                          the server sent a disconnect packet. reason: the packet's
                          reason string (JSON chat text). loggedIn: true for a kick
                          after login, false for one during login. The 'end' event
                          follows when the connection closes.
  'error' (err)           an error of the protocol client. With the createBot option
                          logErrors true (the default) and hideErrors false, the bot has
                          a listener that prints err with console.log.
  'end' (reason)          the connection is closed. reason: the string given to bot.end
                          or bot.quit, or 'socketClosed' when the socket closed without
                          such a call. The physics timer stops here: no more ticks.

bot.end(reason)
  reason: string, optional. Closes the connection through the protocol client and
  keeps reason for the 'end' event. Returns undefined at once. 'end' is emitted when
  the socket has closed.

bot.quit(reason = 'disconnect.quitting')
  Calls bot.end(reason). A reason of null or undefined becomes 'disconnect.quitting'.

After 'end' the bot object keeps its fields with their last values. No 'physicsTick' is
emitted any more, so bot.waitForTicks rejects at its time limit.
