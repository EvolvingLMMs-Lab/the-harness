guide("window-open-close"): opening a window on a block or an entity, bot.currentWindow,
closing, and the window events.

bot.currentWindow                    the open Window, or null
  Set when the server's open-window packet arrives (before 'windowOpen' is emitted). Set
  to null by bot.closeWindow, by a close-window packet from the server, and by a 'login'
  packet. bot.inventory is not stored in bot.currentWindow. The Window fields and
  methods are in guide("window-object"); the window types in guide("window-types").

bot.openBlock(block, direction, cursorPos) -> Promise<Window>
  Calls bot.activateBlock(block, direction, cursorPos) without awaiting it (look at the
  block centre, send one right click on it; guide("block-activate")), then waits for the
  next 'windowOpen' event, 20000 ms at most.
  Resolves with the Window. Rejects with 'Event windowOpen did not fire within timeout of
  20000ms'. It checks no distance and not what kind of block it is.

bot.openEntity(entity) -> Promise<Window>
  Calls bot.activateEntity(entity) (guide("entity-use")) without awaiting it, then waits
  for the next 'windowOpen' event the same way, with the same 20000 ms limit and the same
  error.

How a window opens.
  On an open-window packet the Window is created from the packet's id, type and title and
  stored in bot.currentWindow. 'windowOpen' is emitted once the window's items are known:
  at once when a window-items packet with that id came first, otherwise when it arrives.
  A horse's window (open-horse-window packet) has type 'HorseWindow', title 'Horse'.

Calls added to every opened window.
  They are put on the Window when its open-window packet is handled, before 'windowOpen'
  is emitted: the window in bot.currentWindow has them, whichever call or packet opened
  it. bot.inventory does not have them.
window.close() -> Promise<void>
  Calls bot.closeWindow(window) (below), emits 'close' on the window, and returns the
  promise of bot.closeWindow. The close packet, the copy into bot.inventory,
  bot.currentWindow = null, the bot event 'windowClose' (window), the click outside the
  inventory window and the 'close' event all happen before it returns. The promise
  resolves when that click is answered or has failed (5000 ms at most). It does not
  reject.
window.deposit(itemType, metadata, count, nbt) -> Promise<void>
  Moves count items of that id from the window's inventory section (inventoryStart to
  inventoryEnd - 1) to its container section (0 to inventoryStart - 1), with bot.transfer.
window.withdraw(itemType, metadata, count, nbt) -> Promise<void>
  First it checks bot.inventory.emptySlotCount(): 0 rejects with 'Unable to withdraw, Bot
  inventory is full.', also when a stack of the same item has room; nothing is sent.
  While a window is open bot.inventory does not follow it (guide("inventory-updates")):
  the check reads the inventory as it was when the window opened.
  Otherwise it moves count items of that id from the container section to the inventory
  section, with bot.transfer.
Both.
  itemType: numeric item id. metadata: null or undefined matches any. count: null or
  undefined is 1. nbt: null or undefined matches any; else only items whose nbt is equal.
  The clicks of bot.transfer, step by step: guide("window-transfer"). In a loop until
  count items are moved: with an empty cursor, the lowest numbered source slot that holds
  the item is left-clicked (its whole stack goes on the cursor); the destination slot is
  the lowest numbered stack of the same item that is not full, else the lowest numbered
  empty slot; the cursor stack goes in with one left click when all of it is within count
  and fits, else with right clicks. At the end the rest of the cursor is put back in the
  source range: on a stack that is not full, else an empty slot, else the slot it came
  from; what is then still on the cursor is thrown on the ground.
  Rejects with:
    "Can't find NAME in slots [A - B], (item id: ID)": no source slot holds the item, or
      the source ran out before count items were moved. The items moved so far stay
      moved. A - B is the source range, B excluded.
    'destination full': no stack with room and no empty slot in the destination. The
      stack picked up stays on the cursor (window.selectedItem).
    AssertionError 'Invalid itemType': the id is not an item id.
    "Server didn't respond to transaction for clicking on slot S on window with id W.":
      one click got no answer within 5 seconds.
    'Server rejected transaction for clicking on slot S, on window with id W.'

bot.closeWindow(window) -> Promise
  1. Sends a close-window packet with window.id.
  2. Copies the window's inventory section into bot.inventory (guide("inventory-updates")).
  3. Sets bot.currentWindow to null and emits 'windowClose' (window).
  4. Sends one left click outside the window (slot -999) on bot.inventory and returns its
     promise with errors swallowed: it resolves when the server confirms that click, or
     after 5000 ms when it does not. It does not reject.
  It does not check that window is the open window.

Events on bot.
'windowOpen' (window)                when a window is open and its items are loaded
'windowClose' (window)
  Emitted by bot.closeWindow; by a close-window packet from the server (argument: the
  window that was open, or null); and by a 'login' packet while a window is open.
Events on a window.
'close' ()                           from window.close() only
'updateSlot' (slot, oldItem, newItem), 'updateSlot:N' (oldItem, newItem)   each slot write
