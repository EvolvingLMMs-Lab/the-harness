guide("entity-events"): every entity event on bot, its arguments and its exact moment.

All are emitted on bot (bot.on(name, listener)). The entity argument is the Entity
object from bot.entities. Events about a hit or a death carry no attacker and no amount.

Appearing and disappearing.
  'entitySpawn' (entity)
    A player, living entity, non-living entity or experience orb is announced by the
    server, after its fields are set. Also emitted with bot.entity on every 'spawn' event
    of the bot. For a dropped item it comes before the item's metadata: see 'itemDrop'.
  'entityGone' (entity)
    The server removes the entity. Emitted before entity.isValid becomes false and before
    the entity is deleted from bot.entities.
  'itemDrop' (entity)
    A metadata packet for an entity named 'item' contains an item stack. From this moment
    entity.getDroppedItem() returns the Item. Emitted again on each later such packet.
  'entityPlaced' (entity)
    bot.placeEntity found the entity it placed: guide("place-entity").

Moving.
  'entityMoved' (entity)
    After each relative move, look, move-and-look, teleport or head rotation packet for
    the entity. Not emitted for velocity packets.

What happens to an entity.
  'entityHurt' (entity)          entity status 2, and animation 1
  'entityDead' (entity)          entity status 3
  'entitySwingArm' (entity)      animation 0
  'entityWake' (entity)          animation 2
  'entityEat' (entity)           animation 3
  'entityCriticalEffect' (entity)        animation 4
  'entityMagicCriticalEffect' (entity)   animation 5
  'entityTaming' (entity)        entity status 6
  'entityTamed' (entity)         entity status 7
  'entityShakingOffWater' (entity)       entity status 8
  'entityEatingGrass' (entity)   entity status 10
  'entityHandSwap' (entity)      entity status 55, after equipment[0] and [1] are swapped
  'entitySleep' (entity)         a metadata packet sets the entity's pose to 2
  Other status and animation numbers emit nothing. After 'entityDead' the entity stays in
  bot.entities with isValid true until 'entityGone'.

State changes.
  'entityUpdate' (entity)        after every metadata packet for the entity
  'entityEquip' (entity)         after every equipment packet for the entity
  'entityAttributes' (entity)    after every attributes packet for the entity
  'entityEffect' (entity, effect)
    An effect packet; effect is { id, amplifier, duration }, already stored in
    entity.effects[id].
  'entityEffectEnd' (entity, effect)
    An effect removal packet; effect is the object that was stored in entity.effects, or
    { id, amplifier: -1, duration: -1 } when none was stored.
  'entityCrouch' (entity)
    A metadata packet with key 0 has bit 0x02 set. Emitted on every such packet, also
    when the entity was already crouching.
  'entityUncrouch' (entity)
    A metadata packet with key 0 has bit 0x02 clear and entity.crouching was true.
  'entityElytraFlew' (entity)
    A metadata packet with key 0 has bit 0x80 set and entity.elytraFlying was not true.
  'usedFirework' (fireworkEntityId)
    A firework rocket attached to the bot is seen: guide("entity-own").

Riding and picking up.
  'entityAttach' (entity, vehicle)       attach packet with a vehicle id other than -1
  'entityDetach' (entity, vehicle)       attach packet with vehicle id -1; vehicle is the
                                         value entity.vehicle had before
  'mount', 'dismount' (vehicle)          about the bot itself: guide("mount-riding")
  'playerCollect' (collector, collected)
    The server reports that the entity collector picked up the entity collected.
    collector === bot.entity when the bot picked it up. The event carries no count, and
    the handler does not remove collected from bot.entities.

Players joining and leaving: guide("player-list").
On 1.16.1 the packets behind 'entityHurt' (entity, source) with a source, behind a
thunderbolt 'entitySpawn' with entity.type 'global', and behind 'entitySleep' from a bed
packet do not exist.
