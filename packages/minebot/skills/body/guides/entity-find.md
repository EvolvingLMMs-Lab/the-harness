guide("entity-find"): bot.entities, bot.nearestEntity, bot.entityAtCursor.

bot.entities
  Object keyed by entity id; each value is an Entity (guide("entity-object")). It holds
  every entity the server has announced and not yet removed: players, mobs, dropped
  items, projectiles, experience orbs, vehicles, and bot.entity itself. An id that a
  packet names before the entity is announced is also in it, with name and type
  undefined. An entity is deleted from it when the server removes it. The object is
  replaced by an empty one on each login packet. Paintings are not in it.
  Object.values(bot.entities) gives the list.

bot.entity
  The bot's own Entity: guide("entity-own").

bot.nearestEntity(match = (entity) => true) -> Entity | null
  Goes through every Entity in bot.entities, skips bot.entity and every entity for which
  match(entity) is falsy, and returns the one with the smallest straight-line distance
  from bot.entity.position to entity.position (feet to feet, measured in three
  dimensions). With equal distances the first one found is returned. Returns null when
  nothing passes. There is no distance limit and no line-of-sight check. match is called
  with one argument, the Entity. Entities with undefined name or type are passed to
  match too.

bot.entityAtCursor(maxDistance = 3.5) -> Entity | null
  Returns the entity the bot's view ray hits first.
  1. Calls bot.blockAtCursor(maxDistance). When a block is hit, maxDistance is replaced by
     the distance from bot.entity.position (the feet) to the point where the ray meets
     the block.
  2. Takes every Entity in bot.entities whose type is not 'object', whose username is not
     bot.username, and whose position is at most maxDistance from bot.entity.position
     (feet to feet).
  3. Casts a ray from bot.entity.position raised by bot.entity.eyeHeight, in the
     direction of bot.entity.yaw and bot.entity.pitch.
  4. For each entity, tests the ray against the box width x height x width standing on
     entity.position. A hit counts when the entity is not behind the bot (the vector to
     its feet has a non-negative dot product with the view direction).
  5. Returns the hit entity whose hit point is nearest to bot.entity.position and nearer
     than maxDistance, or null when there is none.
  The yaw and pitch used are the bot's current values; the call turns no head.

bot.findPlayer(filter), bot.findPlayers(filter)
  Search among the player entities in bot.entities: guide("player-list").

Going to an entity that was found.
  bot.nearestEntity measures in a straight line, through walls, water and rock. Nothing
  moves the body to it: code moves it with the keys and the head (guide("control-keys"),
  guide("look")). Whether the eyes see it: bot.entityInSight(entity) and bot.inSight
  (guide("raycast")).
