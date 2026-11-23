guide("window-object-changes"): the Window methods that change the local copy of a
window, and the window's slot events.

Everything on this page changes only the local Window object. None of these calls sends
a packet; the server's inventory stays as it is. The library calls them when packets
arrive and when the server accepts a click.

window.updateSlot(slot, newItem)
  Sets newItem.slot = slot (when newItem is not null), stores newItem in
  window.slots[slot], then emits 'updateSlot' and 'updateSlot:N'.

Events on a window.
'updateSlot' (slot, oldItem, newItem)
  After every updateSlot call: packets, accepted clicks, the copy made when a window
  closes. It fires also when newItem equals oldItem. A click that only changes the count
  of a stack already in a slot writes item.count and emits nothing.
'updateSlot:N' (oldItem, newItem)    the same for slot number N
'close' ()                           from window.close()

window.acceptClick(click, gamemode = 0)
  Applies one click; see guide("window-click-modes"). It works through the methods below.

window.mouseClick(click), window.shiftClick(click), window.numberClick(click),
window.middleClick(click, gamemode), window.dropClick(click)
  The handlers of modes 0, 1, 2, 3 and 4.
window.dragClick(click, gamemode), window.doubleClick(click)
  Modes 5 and 6: both throw an AssertionError 'unimplemented'.

window.swapSelectedItem(slot, item)
  Puts the cursor item in the slot and makes item the cursor item.
window.splitSlot(item)
  Makes a new cursor Item with count / 2 rounded up; item keeps the rest; a slot left at
  count 0 becomes null.
window.dropSelectedItem(untilEmpty)
  untilEmpty true: the cursor becomes null. false: the cursor count goes down by 1, and
  the cursor becomes null at 0.
window.fillSlotWithSelectedItem(item, untilFull)
  untilFull true: moves cursor items onto item up to stackSize. false: moves one, when
  item is not full. The cursor becomes null at count 0.
window.fillSlotWithItem(itemToFill, itemToTake)
  Moves count from itemToTake onto itemToFill up to stackSize; a slot emptied this way
  becomes null.
window.fillSlotsWithItem(slots, item, lastToFirst = false)
  Calls fillSlotWithItem for each Item of the array slots until item.count is 0.
window.dumpItem(item, start, end, lastToFirst = false)
  Moves item to the first empty slot of the range (the last one with lastToFirst), unless
  there is none or it is the crafting result slot.
window.fillAndDump(item, start, end, lastToFirst = false)
  Fills the stacks of the same item that are not full in start to end - 1, then dumpItem
  for what is left.

window.clear(blockId, count) -> number
  Removes items from the local inventory section and returns how many were removed. It
  goes from slot inventoryEnd down to hotbarStart, then from inventoryStart up to
  hotbarStart - 1. blockId falsy: every item matches; otherwise items whose type equals
  blockId. count falsy: all matching stacks are removed; otherwise it stops once count
  items are removed, shrinking the last stack.
