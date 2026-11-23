guide("entity-own"): bot.entity, bot.usingHeldItem, bot.fireworkRocketDuration.

bot.entity
  The bot's own Entity (guide("entity-object")). Undefined before the login packet. On
  each login packet a new Entity is created for the bot's entity id, stored in
  bot.entities, and given: username = bot.username, type 'player', name 'player',
  height 1.8, width 0.6, eyeHeight 1.62. It has no kind, displayName or entityType.
  bot.entity.position      Vec3 of the feet; the eyes are bot.entity.eyeHeight above it
  bot.entity.velocity      Vec3, blocks per tick
  bot.entity.yaw, bot.entity.pitch       radians; yaw 0 faces -z, PI/2 faces -x; pitch
                           positive is up
  The physics of the bot sets these every tick, together with bot.entity.onGround,
  bot.entity.isInWater, bot.entity.isInLava, bot.entity.isInWeb,
  bot.entity.isCollidedHorizontally, bot.entity.isCollidedVertically and
  bot.entity.elytraFlying.
  bot.entity.equipment     from each 'spawn' event of the bot this is read-only and
                           computed from the inventory at the moment it is read:
                           [bot.heldItem, slot 45 (off hand), slot 8 (boots),
                           slot 7 (leggings), slot 6 (chestplate), slot 5 (helmet)]
  bot.entity.heldItem      bot.entity.equipment[0]
  bot.entity.height, bot.entity.eyeHeight        become 1.5 and 1.27 when the server sends
                           the bot's own crouch flag, and 1.8 and 1.62 when it clears
  bot.entity.health, bot.entity.food are undefined; the values are bot.health, bot.food.
  'entitySpawn' is emitted with bot.entity on every 'spawn' event of the bot.

bot.usingHeldItem
  Boolean, false at start.
  Set to true by bot.activateItem (bot.consume calls it).
  Set to false by: bot.deactivateItem; every entity status packet, for any entity; a
  'heldItemChanged' event where the held item's type or count differs from the previous
  one; a cooldown packet for the type of the held item, or any cooldown packet while the
  hand is empty.
  No code reads it. Writing it changes nothing else.

bot.fireworkRocketDuration
  Number of physics ticks of firework boost left. 0 at start.
  Set when a metadata packet of an entity named 'firework_rocket' says the rocket is
  attached to the bot's entity id (metadata key 8 holds the id plus 1). This is done
  once per rocket entity id:
    flight = the Fireworks.Flight number in the rocket item's NBT (metadata key 7), or 1
             when the item has no NBT or the value is not a number
    bot.fireworkRocketDuration = 10 * (flight + 1) + a random whole number from 0 to 11
  and then 'usedFirework' (fireworkEntityId) is emitted, with the rocket's entity id.
  A second rocket replaces the value; it is not added.
  Each physics tick while the value is above 0: if bot.entity.elytraFlying is false the
  value becomes 0; otherwise the velocity is pulled toward 1.5 blocks per tick along the
  view direction (each axis: v += look * 0.1 + (look * 1.5 - v) * 0.5) and the value
  drops by 1.
  It also becomes 0 when a metadata packet for the bot's own entity has the elytra flag
  (key 0, bit 0x80) clear; the list of rockets already counted is emptied then.
  Writing a number to it starts or stops the boost in the physics the same way.
