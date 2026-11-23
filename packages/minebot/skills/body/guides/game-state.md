guide("game-state"): bot.game and all its fields, the 'login' and 'game' events, what a
change of dimension does.

bot.game
  An object, empty at creation. Its fields are set from the login packet and from each
  respawn packet (the server sends one after a death and at every change of dimension).

  bot.game.dimension      'overworld', 'the_nether' or 'the_end': the packet's dimension
                          name without the 'minecraft:' prefix. Login and respawn.
  bot.game.gameMode       'survival', 'creative', 'adventure' or 'spectator', from the
                          packet's number 0 to 3; any other number gives 'survival'.
                          Login, respawn, and a game mode change packet.
  bot.game.levelType      'flat' when the packet's isFlat is true, else 'default'.
  bot.game.hardcore       boolean. At login: (the packet's game mode number & 4) is not
                          0. Every respawn packet sets it to false.
  bot.game.minY           0. Login and respawn.
  bot.game.height         256. Login and respawn.
  bot.game.maxPlayers     number from the login packet.
  bot.game.enableRespawnScreen   true when the login packet says so; else not set.
  bot.game.serverViewDistance    number (chunks) from the login packet; not set when 0.
  bot.game.serverBrand    string: the server's brand, set when the server sends it on
                          the 'minecraft:brand' channel; undefined before.
  bot.game.difficulty     undefined on 1.16.1. The module looks the difficulty up by
                          number; the 1.16.1 packet gives it as a name, and the lookup
                          finds nothing.

At the login packet, in this order.
  1. The fields above are set.
  2. 'login' is emitted.
  3. 'game' is emitted.
  4. The client brand (createBot option brand, default 'vanilla') is sent to the server.
  When 'login' is emitted, bot.entity and bot.username are already set.

At a respawn packet.
  dimension, gameMode, levelType, hardcore, minY and height are set again, then 'game'
  is emitted. In the same packet other modules emit 'respawn', set bot.isAlive to false
  and stop the simulation until the server's next position packet.

Events.
  'login' ()       once for each login packet
  'game' ()        after the login packet; after each respawn packet; after a game mode
                   change packet; and each time the server sets the world spawn point
                   (bot.spawnPoint)

End of the game.
  When the server sends the 'win game' state with value 1 (the end credits), the module
  answers with the 'perform respawn' client command at once.
