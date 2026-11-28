guide("entity-use"): right-clicking an entity: useOn, activateEntity, activateEntityAt.

All three send one interact packet for the main hand. None checks distance, line of
sight or entity.isValid, and none waits for an answer from the server. The packet names
the entity and the hand; it does not name the item in the hand.

bot.useOn(target)
  Synchronous, returns undefined. Sends an interact packet for target.id with the main
  hand and the bot's sneak control state (bot.getControlState('sneak')). Turns no head.
  Throws TypeError when target is null or undefined.

bot.mount(target)
  Sends exactly the same packet as bot.useOn(target); getting on a vehicle:
  guide("mount-riding").

bot.activateEntity(entity) -> Promise<void>
  1. Awaits bot.lookAt(entity.position.offset(0, 1, 0), false): the head turns toward the
     point 1 block above the entity's feet.
  2. Sends one use-entity packet: target entity.id, mouse 0 (interact), hand 0 (the main
     hand), sneaking false, whatever the sneak control state is.
  Resolves with undefined right after the packet is sent.
  bot.openEntity(entity) calls this without awaiting it and then waits for the
  'windowOpen' event.

bot.activateEntityAt(entity, position) -> Promise<void>
  position is a Vec3 in world coordinates.
  1. Awaits bot.lookAt(position, false).
  2. Sends one use-entity packet: target entity.id, mouse 2 (interact at), hand 0 (the
     main hand), sneaking false, and x, y, z equal to position - entity.position (the
     offset from the entity's feet).
  Resolves with undefined right after the packet is sent.
  The Vec3 passed as position is changed in place: after the call it holds the offset
  position - entity.position.
