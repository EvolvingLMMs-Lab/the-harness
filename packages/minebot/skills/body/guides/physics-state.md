guide("physics-state"): the movement state the simulation keeps on bot.entity, and the
effects, enchantments and attributes it reads.

Written to bot.entity at every simulated tick.
  bot.entity.position    Vec3, the middle of the bottom of the body. A new Vec3 object is
                         put here at each tick: a reference taken earlier keeps the old
                         numbers. A position packet from the server changes the numbers
                         of the current object in place.
  bot.entity.velocity    Vec3, blocks a tick; a new object at each tick. It is the
                         velocity after the tick's gravity and friction (what the next
                         tick starts from), not the distance just moved.
  bot.entity.onGround    boolean. true when the last move was stopped by a block while
                         going down. true on a new Entity before the first tick; false
                         right after a position packet from the server.
  bot.entity.isInWater   boolean; undefined before the first tick. guide("physics-liquid")
  bot.entity.isInLava    boolean; undefined before the first tick
  bot.entity.isInWeb     boolean; undefined before the first tick
  bot.entity.isCollidedHorizontally   boolean: the last move was cut along x or z
  bot.entity.isCollidedVertically     boolean: the last move was cut in height
  bot.entity.elytraFlying   set to true by the server's entity data; the simulation sets it
                         to false: guide("elytra")
  bot.jumpTicks, bot.jumpQueued       guide("control-keys")
  bot.fireworkRocketDuration          guide("elytra")
  Writing any of these changes what the next tick starts from. bot.entity.position
  written by code is sent to the server by the next position update.

Read at every tick, not written.
  bot.entity.yaw, bot.entity.pitch    guide("look")
  the seven keys                      guide("control-keys")
  bot.entity.attributes               an object keyed by attribute name, filled from the
    server's attribute packets: { value, modifiers: [{ uuid, amount, operation }] }.
    The simulation reads 'generic.movement_speed' only. Its number is: value, plus the
    amounts of the operation 0 modifiers; then plus that sum times the amount of each
    operation 1 modifier; then multiplied by (1 + amount) for each operation 2 modifier.
    A modifier with the sprint uuid is dropped first and added again (amount 0.3,
    operation 2) while the sprint key is held. Absent: 0.1.
  bot.entity.effects                  keyed by effect id: { id, amplifier, duration }.
    The level of an effect is amplifier + 1, or 0 without the effect.
      Jump Boost       0.1 more jump speed for each level
      Slow Falling     gravity times 0.125 while velocity.y is 0 or less
      Levitation       velocity.y moves to 0.05 * level in place of gravity; ends an
                       elytra flight
      Dolphin's Grace  horizontal factor 0.96 in water
      Speed, Slowness  the levels are read and not used. A change of walking speed
                       comes from the 'generic.movement_speed' attribute the server sends.
  bot.inventory.slots[8]              the boots. The level of the depth_strider
    enchantment in the item's nbt is read: guide("physics-liquid"). No other enchantment
    is read.
  bot.inventory.slots[6]              the chest slot. An item named 'elytra' there lets
    an elytra flight go on.

Sizes set at login (by the entities module).
  bot.entity.height 1.8, bot.entity.width 0.6, bot.entity.eyeHeight 1.62. A position
  packet from the server sets bot.entity.height to 1.8 again.
