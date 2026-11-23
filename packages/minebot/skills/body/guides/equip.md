guide("equip"): bot.equip, bot.unequip, the equipment destinations and their slots.

Destinations and their bot.inventory slots.
  'hand'      36 + bot.quickBarSlot (the selected hotbar slot)
  'head' 5    'torso' 6    'legs' 7    'feet' 8    'off-hand' 45
bot.getEquipmentDestSlot(destination) -> number
  Returns the slot above. Any other destination throws an AssertionError
  'invalid destination: X'.

bot.equip(item, destination) -> Promise
  item: an Item, or an item id (number). destination: one of the names above; null,
  undefined or '' means 'hand'.
  1. A number is replaced by bot.inventory.findInventoryItem(id): the first stack of that
     id in slots 9 to 44, lowest slot first (armour, off hand and crafting slots are not
     searched).
  2. When item is null, undefined or not an object: it throws 'Invalid item object in
     equip (item is null or typeof item is not object)'.
  3. The source slot is item.slot. When it equals the destination slot: done, nothing sent.
  4. Destination other than 'hand': bot.moveSlotItem(source, destination slot): left
     click the source, left click the destination, and when the cursor then holds an item
     (what was in the destination), left click the source again to put it there.
  5. Destination 'hand', source in the hotbar (36 to 44): bot.setQuickBarSlot(source -
     36). No click; done without waiting for the server.
  6. Destination 'hand', source elsewhere: the target is the first empty hotbar slot; with
     a full hotbar it is 36 + n, where n starts at 0 and goes up by 1 (back to 0 after 8)
     each time this case is used. bot.setQuickBarSlot(target - 36), then
     bot.moveSlotItem(source, target); the item that was in the target ends in the source
     slot.
  Resolves with nothing. Rejects with the errors of bot.clickWindow
  (guide("window-click")). It does not check that the item fits the destination; the
  clicks are sent as they are. The slot numbers are bot.inventory numbers and the clicks
  go to bot.currentWindow when a window is open, where the same numbers are other slots.

bot.unequip(destination) -> Promise
  'hand':
  1. The first empty hotbar slot, if any, is selected with bot.setQuickBarSlot; done.
  2. Otherwise it takes bot.inventory.firstEmptyInventorySlot() (9 to 44). With no empty
     slot it calls bot.tossStack(bot.heldItem): the held stack is dropped on the ground.
  3. With an empty slot: left click the held slot, left click the empty slot, and when
     the cursor still holds an item, left click outside the window (drops it).
  Any other destination:
  1. bot.currentWindow not null: AssertionError (a window is open).
  2. The slot comes from bot.getEquipmentDestSlot, then bot.putAway(slot)
     (guide("window-transfer")): a shift click when the inventory has room for the item,
     otherwise a left click and the item is put into slots 9 to 44, or dropped when none
     has room.
  3. It waits for that slot to be written. With nothing in the slot no write happens and
     it rejects after 20000 ms with 'Event updateSlot:N did not fire within timeout of
     20000ms' (N is the slot number).

bot.entity.equipment                 [hand, off hand, feet, legs, torso, head], each an
                                     Item or null, read from bot.inventory
