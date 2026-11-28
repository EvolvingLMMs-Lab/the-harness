guide("player-list"): bot.players, bot.player, bot.findPlayer, the player events.

bot.players
  Object keyed by username; one player object for each player in the server's player
  list, the bot included. Replaced by an empty object on each login packet.
  player.username        string
  player.uuid            string
  player.ping            number, as sent by the server; updated on latency packets
  player.gamemode        number, the game mode id the server sent when the player was
                         added. On 1.16.1 the game mode update of the player list is
                         not applied: the value stays and no event is emitted.
  player.displayName     ChatMessage; the server's display name, or the username
  player.skinData        { url, model, capeUrl } from the player's texture property;
                         model and capeUrl are undefined when absent; skinData is
                         undefined when there is no skin url
  player.entity          the player's Entity while it is in bot.entities. Undefined when
                         the player was added while not in view. Set when the player
                         comes into view. null after the server removes the entity.

bot.player
  The bot's own player object. Set when the player list entry whose entity is bot.entity
  is added or added again. Undefined before that.

bot.username             the bot's name; set on each login packet
bot.uuidToUsername       object: uuid -> username, for the players in bot.players

bot.findPlayer(filter), bot.findPlayers(filter)
  One function under two names. It searches the Entity objects in bot.entities with
  type 'player' (players in view, bot.entity included), not bot.players.
  filter null             returns an array of all of them
  filter a string         compares with entity.username, ignoring case; returns null for
                          no match, the Entity for one match, an array for several
  filter a RegExp         returns an array of those whose username matches
  filter a function       returns an array of those for which filter(entity) is truthy
  filter anything else, or left out       returns an empty array

Events on bot.
  'playerJoined' (player)
    A player list entry is added for a uuid that was not listed. The player object is
    already in bot.players.
  'playerUpdated' (player)
    An entry is added again for a uuid already listed (ping, gamemode, displayName,
    skinData and entity are set again), or a latency or display name update arrives for
    a listed player.
  'playerLeft' (player)
    A listed player is removed from the player list. player.entity is set to null and
    the player is deleted from bot.players and bot.uuidToUsername before the event. The
    removal of the bot's own entry is ignored.
  A player entering or leaving view is 'entitySpawn' and 'entityGone' with the player's
  Entity: guide("entity-events"). A player entity is created only when its uuid is
  already in bot.uuidToUsername.
