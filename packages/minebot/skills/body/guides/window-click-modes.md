guide("window-click-modes"): what each click mode does to the local slots and cursor of a
window once the server accepts it (window.acceptClick).

"Cursor" is window.selectedItem. "Same item" means equal type, metadata and nbt. Each
slot write emits 'updateSlot'. The server makes its own computation; any set-slot packet
it sends afterwards overwrites these results.

Mode 0, left click (mouseButton 0).
  Slot -999: the cursor becomes null (the whole cursor stack is dropped).
  Slot and cursor both hold the same item: the cursor is poured into the slot up to
  stackSize; the rest stays on the cursor. On the crafting result slot it goes the other
  way: the cursor takes from the slot up to stackSize.
  Slot and cursor hold different items: they swap.
  Only one of them holds an item: it moves to the other (pick up, or put down).
  Both empty: nothing.

Mode 0, right click (mouseButton 1).
  Slot -999: the cursor count goes down by 1; at 0 the cursor becomes null.
  Cursor holds an item, slot holds the same item: one item moves to the slot unless the
  slot is full. Slot holds a different item: they swap. Slot empty: one item is placed.
  Cursor empty, slot holds an item, and it is not the crafting result slot: the cursor
  takes the larger half (count / 2 rounded up); the slot keeps the rest.

Mode 1, shift click (mouseButton 0 or 1). An empty slot: nothing.
  The clicked stack first fills stacks of the same item that are not full in the target
  range, then what is left moves to the first empty slot of that range.
  In bot.inventory: from slots 0 to 8 the target is 9 to 44 (filled from the last slot
  backwards when the click is on slot 0, and then an empty slot 45 is taken first); from
  slots 9 to 34 the target is the hotbar 36 to 44; from slots 35 to 45 the target is
  9 to 44.
  In another window: from the container section the target is the inventory section
  (from the last slot backwards when the window has no crafting result slot, or the click
  is on it); from the inventory section the target is slots 0 to inventoryStart - 2.

Mode 2, number key (mouseButton 0 to 8 = hotbar slot window.hotbarStart + mouseButton).
  Cursor holds an item: nothing.
  Slot and hotbar slot both hold items, and the slot is not the crafting result slot:
  they swap. Slot holds an item, hotbar slot empty: the item moves to the hotbar slot.
  Slot empty, hotbar slot holds an item, slot is not the result slot: it moves to the
  slot.
  On the crafting result slot with an occupied hotbar slot: the hotbar item moves to the
  first empty slot of the hotbar, else of the main inventory; when that frees the hotbar
  slot, the result moves into it.

Mode 3, middle click (mouseButton 2): no local change (the code changes the cursor only
  for game mode creative, and mineflayer does not pass the game mode).

Mode 4, drop key. Cursor holds an item, or the slot is empty: nothing.
  mouseButton 0: the slot's count goes down by 1; at 0 the slot becomes null.
  mouseButton 1: the slot becomes null.

Modes 5 and 6: AssertionError 'unimplemented'.

window.acceptClick(click, gamemode = 0) -> [slot numbers] | undefined
  click: { slot, mouseButton, mode, item }, item being the Item in the slot. It applies
  the rules above to the local window only and sends nothing. bot.clickWindow calls it
  when the server accepts. Modes 0 and 4 return the list of changed slot numbers.
  AssertionError 'invalid operation': mode outside 0 to 6; mouseButton outside 0 to 8, or
  not one the mode takes (modes 0, 1 and 4: 0 or 1; mode 3: 2); slot not -999, not from
  0 to inventoryEnd - 1, and not 45 of a 'minecraft:inventory' window.
  Each mode is handled by one method (mouseClick, shiftClick, numberClick, middleClick,
  dropClick): guide("window-object-changes").
  The names acceptOutsideWindowClick, acceptInventoryClick,
  acceptNonInventorySwapAreaClick, acceptSwapAreaLeftClick, acceptSwapAreaRightClick and
  acceptCraftingClick are the same function.
