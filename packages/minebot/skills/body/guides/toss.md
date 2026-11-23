guide("toss"): bot.toss and bot.tossStack: dropping items on the ground.

bot.toss(itemType, metadata, count) -> Promise
  itemType: an item id (number). metadata: null matches every item. count: how many to
  drop; null or undefined means 1.
  It calls bot.transfer (guide("window-transfer")) on the window bot.currentWindow, or
  bot.inventory when no window is open, with the source range window.inventoryStart to
  window.inventoryEnd - 1 (for bot.inventory: slots 9 to 44) and the destination -999
  (outside the window). Steps, repeated until count is 0:
  1. When the cursor does not hold itemType, it finds the first stack of itemType in the
     source range (lowest slot first) and left clicks it: the whole stack goes on the
     cursor.
  2. When the cursor holds no more than the remaining count: one left click outside drops
     the whole cursor stack; count goes down by that many.
     Otherwise: one right click outside drops one item; count goes down by 1. Each click
     waits for the server's confirmation before the next.
  3. At count 0, what is left on the cursor is put back: onto a stack of the same item
     that is not full in the source range, else into the first empty slot there, else
     onto the slot the first stack came from, and what still remains is dropped.
  Resolves with nothing.
  Rejects with:
  - "Can't find NAME in slots [START - END], (item id: ID)" when the source range holds
    no (more) stack of the item. Items dropped before that stay dropped.
  - AssertionError 'Invalid itemType' when the id is not an item id.
  - the errors of bot.clickWindow (guide("window-click")).
  Armour slots, the off hand and the crafting grid are outside the source range.

bot.tossStack(item) -> Promise
  item: an Item. A falsy item throws an AssertionError.
  1. Left click on item.slot (the stack goes on the cursor).
  2. Left click outside the window (slot -999): the cursor stack is dropped.
  3. bot.closeWindow(bot.currentWindow || bot.inventory): a close-window packet is sent,
     'windowClose' is emitted, and one more left click outside is sent and awaited (its
     failure is ignored). An open chest, furnace or other window is closed by this step.
  Resolves with nothing. Rejects with the errors of bot.clickWindow from steps 1 and 2.
  item.slot is used as a slot number of the window that is open at that moment: for an
  Item taken from bot.inventory while another window is open, that number points at a
  different slot of the open window.

Where the item lands, and whether the bot picks it up again, is decided by the server.

bot.tossedItem(entity) -> boolean
  true for an item entity that appeared within 4 blocks of the body less than 1.5 s
  after the start or the end of a toss or tossStack call, for 5 minutes after it
  appeared and while it is in bot.entities; false for every other entity. It uses no channel and is not gated.
