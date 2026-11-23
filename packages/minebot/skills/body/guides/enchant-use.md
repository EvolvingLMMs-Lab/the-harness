guide("enchant-use"): the methods of an open enchanting table: put, enchant, take.

enchantmentTable is the object bot.openEnchantmentTable resolves with; see
guide("enchant-table") for its slots and options.

Slot numbers.
  putTargetItem and putLapis read item.slot as a slot of the table window. The items of
  enchantmentTable.items() carry those numbers (2 to 37). An Item taken from
  bot.inventory carries a slot of the inventory window (9 to 44); the same item is at
  slot - 7 in the table window.

enchantmentTable.putTargetItem(item) -> Promise<void>
  bot.moveSlotItem(item.slot, 0): left-clicks item.slot (the stack goes on the cursor),
  then left-clicks slot 0. When slot 0 already held another item, that item ends on the
  cursor (enchantmentTable.selectedItem); the code does not put it down.
enchantmentTable.putLapis(item) -> Promise<void>
  bot.moveSlotItem(item.slot, 1): the same two clicks with slot 1. The whole stack in
  item.slot is moved.

enchantmentTable.enchant(choice) -> Promise<Item>
  choice: 0, 1 or 2, the index in enchantmentTable.enchantments; a string is parsed.
  1. The table is not in the ready state: waits for the 'ready' event, 20 seconds at
     most; else rejects with 'Event ready did not fire within timeout of 20000ms'.
  2. enchantments[choice].level is -1: rejects with an AssertionError. A choice outside
     0 to 2: rejects with a TypeError.
  3. Sends the enchant packet with the window id and choice.
  4. Waits for slot 0 of the window to be written, 20 seconds at most, and resolves with
     the new Item of slot 0. No write within 20 seconds: rejects with
     'Event updateSlot:0 did not fire within timeout of 20000ms'.
  The code does not check bot.experience.level against the option's level and does not
  check the lapis slot before sending. The item stays in slot 0.

enchantmentTable.takeTargetItem() -> Promise<Item>
  Reads slot 0. Empty: rejects with an AssertionError. Else bot.putAway(0): one
  shift-click when the inventory part has a stack to join or an empty slot; else a
  left-click, and the cursor is thrown on the ground. It waits for slot 0 to change,
  20 seconds at most, and resolves with the Item that was in slot 0.

Every click waits for the server's confirmation, 5 seconds at most; it rejects with
"Server didn't respond to transaction for clicking on slot S on window with id W." or
'Server rejected transaction for clicking on slot S, on window with id W.'

enchantmentTable.deposit, withdraw, close(): guide("window-open-close").
enchantmentTable.items(): guide("window-object").
