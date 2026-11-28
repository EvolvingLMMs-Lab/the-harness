guide("creative"): the bot.creative calls: setting inventory slots and flying.

None of these calls tests the game mode. Each does the steps below in any mode. What the
server does with the packets in survival mode is the server's decision; the waits and
errors below say what the bot does when the expected answer does not come.

bot.creative.setInventorySlot(slot, item, waitTimeout = 400) -> Promise
  slot: a bot.inventory slot number 0 to 44; outside that range: AssertionError.
  item: an Item, or null to empty the slot. waitTimeout is not used on 1.16.1.
  1. When the slot already holds an equal item (type, count, metadata, nbt): it returns
     at once and sends nothing.
  2. When an earlier call for the same slot is still waiting: it throws 'Setting slot N
     cancelled due to calling bot.creative.setInventorySlot(N, ...) again'.
  3. It sends one set-creative-slot packet with the slot and the item.
  4. It waits for bot.inventory to emit 'updateSlot:N' with a new item that matches:
     null when item is null, otherwise the same name, count and metadata. 5000 ms at
     most.
  Resolves with nothing when the matching update arrives. Rejects with 'Event
  updateSlot:N did not fire within timeout of 5000ms' when it does not. The local
  inventory is changed only by the server's answer.

bot.creative.clearSlot(slot) -> Promise
  bot.creative.setInventorySlot(slot, null).

bot.creative.clearInventory() -> Promise
  Calls bot.creative.setInventorySlot(item.slot, null) for every item in
  bot.inventory.slots at the same time and waits for all. An item in slot 45 (off hand)
  makes it reject with the AssertionError of the slot range.

bot.creative.startFlying()
  Synchronous. The first call stores bot.physics.gravity. Every call sets
  bot.physics.gravity to 0. It sends nothing; the local physics stops pulling the bot
  down.

bot.creative.stopFlying()
  Synchronous. Sets bot.physics.gravity back to the stored value. Without an earlier
  startFlying (or flyTo) the stored value is null and gravity becomes null.

bot.creative.flyTo(destination) -> Promise
  destination: a Vec3.
  1. bot.creative.startFlying().
  2. While the distance to destination is more than 0.5: it sets bot.physics.gravity to
     0 and bot.entity.velocity to (0, 0, 0), adds a step of length 0.5 toward the
     destination to bot.entity.position, and sleeps 50 ms (10 blocks a second).
  3. It sets bot.entity.position to destination and waits for the next 'move' event,
     with no time limit.
  Resolves with nothing. It moves in a straight line and writes the position directly:
  it looks at no blocks on the way. Gravity stays 0 afterwards until
  bot.creative.stopFlying(). The positions are sent to the server by the bot's normal
  position updates.
