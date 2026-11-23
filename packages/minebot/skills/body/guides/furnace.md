guide("furnace"): bot.openFurnace and the furnace window: slots, putting in, taking out.

bot.openFurnace(furnaceBlock) -> Promise<furnace>
  Calls bot.openBlock(furnaceBlock): the bot turns its head to the centre of the block,
  sends one use-block packet on the block's top face, and waits for the bot event
  'windowOpen', 20 seconds at most ('Event windowOpen did not fire within timeout of
  20000ms'). The code checks no distance and does not check the block before clicking.
  The window that opened is accepted when its type starts with 'minecraft:furnace',
  'minecraft:blast_furnace' or 'minecraft:smoker'. Any other window: rejects with
  'This is not a furnace-like window'; that window stays open (bot.currentWindow).
  Resolves with the window, with the members below added.

Slots of the furnace window.
  0 input, 1 fuel, 2 output. 3 to 38: the bot's inventory (30 to 38 the hotbar).
  furnace.inventoryStart is 3, furnace.inventoryEnd is 39.

furnace.inputItem() -> Item | null     furnace.slots[0]
furnace.fuelItem() -> Item | null      furnace.slots[1]
furnace.outputItem() -> Item | null    furnace.slots[2]

furnace.putInput(itemType, metadata, count) -> Promise<void>      into slot 0
furnace.putFuel(itemType, metadata, count) -> Promise<void>       into slot 1
  itemType: numeric item id. metadata: null (items of 1.16.1 have metadata 0). count: how
  many items to move; null or undefined: 1.
  Calls bot.transfer from slots 3 to 38 to the one slot. It left-clicks the lowest
  numbered inventory slot that holds the item, then clicks the furnace slot: a left-click
  when the whole cursor stack is within count, right-clicks for single items otherwise.
  Further stacks are picked up until count items are moved; the rest of the cursor goes
  back to the inventory part.
  Rejects with:
    'destination full': the furnace slot holds another kind of item, or a full stack. The
      stack picked up stays on the cursor (furnace.selectedItem).
    "Can't find NAME in slots [3 - 39], (item id: ID)": no inventory slot holds the item,
      or the inventory ran out before count items were moved (the items moved so far stay
      in the furnace).
    AssertionError 'Invalid itemType': the id is not an item id.

furnace.takeInput() -> Promise<Item>
furnace.takeFuel() -> Promise<Item>
furnace.takeOutput() -> Promise<Item>
  Reads the slot's item. Empty slot: rejects with an AssertionError. Else bot.putAway on
  the slot, and resolves with the Item that was in it (the whole stack is taken).
  Input and fuel: one shift-click when the inventory part has a stack to join or an empty
  slot; else a left-click, and the cursor is thrown on the ground.
  Output: a left-click takes the stack on the cursor; the cursor is then put on a stack of
  the same item that is not full, else on an empty slot, else thrown on the ground.
  It waits for the slot to change, 20 seconds at most ('Event updateSlot:N did not fire
  within timeout of 20000ms').

furnace.deposit, furnace.withdraw, furnace.close(), the 'updateSlot' events
  As on every window that is opened: guide("window-open-close").

Every click waits for the server's confirmation, 5 seconds at most; it rejects with
"Server didn't respond to transaction for clicking on slot S on window with id W." or
'Server rejected transaction for clicking on slot S, on window with id W.'

furnace.fuel, furnace.progress and the 'update' event: guide("furnace-progress").
One item smelts in 10 seconds.
