guide("window-transfer"): moving items between slots with several clicks: bot.transfer,
bot.putSelectedItemRange, bot.putAway, bot.moveSlotItem.

Every click below is bot.clickWindow: it goes to bot.currentWindow (or bot.inventory when
none is open), waits for the server's confirmation, and rejects as in
guide("window-click").

bot.transfer(options) -> Promise
  options.window        the window whose slots are read; default bot.currentWindow, or
                        bot.inventory
  options.itemType      item id (number)
  options.metadata      null or undefined: any
  options.nbt           null or undefined: any
  options.count         how many items to move; null or undefined: 1
  options.sourceStart, options.sourceEnd   source slots, end not included
  options.destStart, options.destEnd       destination slots, end not included;
                        destStart -999 drops the items outside the window
  sourceEnd null means sourceStart + 1; destEnd null means destStart + 1 (null only, not
  undefined).
  Repeated until count is 0:
  1. When the cursor does not hold the item: the first stack of itemType in the source
     range is left clicked (picked up). None found: it throws "Can't find NAME in slots
     [START - END], (item id: ID)". An id that is no item: AssertionError
     'Invalid itemType'.
  2. Destination slot: -999, or the first stack of the same item that is not full in the
     destination range, else the first empty slot there. None: it throws
     'destination full' (the cursor still holds the picked-up stack).
  3. With d the count already in the destination slot and c the cursor count:
     a. When m = min(stackSize - d, c) is at most count: one left click on the
        destination moves m items; count goes down by m.
     b. Otherwise, when the destination is a slot and, with t = d + count and
        h = floor(min(d + c, stackSize) / 2), h <= t and 3 + t - h < count: one left
        click puts the cursor stack in, bot.putSelectedItemRange puts any cursor rest
        back in the source range, one right click takes the larger half out (the slot
        keeps h), then t - h right clicks add one item each; count becomes 0.
     c. Otherwise: one right click moves one item; count goes down by 1.
  At count 0 the cursor rest goes back with bot.putSelectedItemRange(sourceStart,
  sourceEnd, window, the slot of the first picked-up stack).
  Resolves with nothing. Items moved before an error stay moved.

bot.putSelectedItemRange(start, end, window, slot) -> Promise
  While window.selectedItem is not null: left click the first stack of the same item that
  is not full in start to end - 1; else left click the first empty slot there; else, with
  slot null, left click outside (drops the cursor stack); with a slot number, left click
  that slot and then left click outside when the cursor still holds an item.

bot.putAway(slot) -> Promise
  Moves the item of one slot of the current window into its inventory section.
  When the inventory section has a stack of the same item that is not full, or an empty
  slot, and the slot is not a result slot (window.craftingResultSlot, or slot 2 of a
  'minecraft:merchant' window): one shift click (mode 1) on the slot.
  Otherwise: one left click on the slot, then bot.putSelectedItemRange(inventoryStart,
  inventoryEnd, window, null).
  Then it waits for 'updateSlot:N' of that slot, 20000 ms at most from the start of the
  call. With an empty slot nothing is written and it rejects with 'Event updateSlot:N did
  not fire within timeout of 20000ms'.

bot.moveSlotItem(sourceSlot, destSlot) -> Promise
  Left click sourceSlot, left click destSlot, emit 'heldItemChanged'. When
  bot.inventory.selectedItem is then not null (the destination held another item), left
  click sourceSlot again, which puts that item there. The test reads the cursor of
  bot.inventory, also while another window is open.

window.deposit, window.withdraw      guide("window-open-close")
bot.toss                             guide("toss")
