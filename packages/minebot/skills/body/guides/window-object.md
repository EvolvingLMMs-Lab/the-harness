guide("window-object"): the Window object: its fields and the methods that read it.

bot.inventory and bot.currentWindow are Window objects; every Window has the fields and
methods of this page. A window has a container section
(slots 0 to inventoryStart - 1) followed by the bot's 36 inventory slots (27 main slots,
then 9 hotbar slots). In bot.inventory the first 9 slots are crafting and armour and slot
45 is the off hand (guide("inventory-read")). The methods that change a window are in
guide("window-object-changes"); close, deposit and withdraw, which only an opened window
has, in guide("window-open-close").

Fields.
window.id                            number: the server's window id; 0 for bot.inventory
window.type                          string, for example 'minecraft:generic_9x3'
window.title                         the title as the server sent it
window.slots                         array of Item | null, indexed by slot number
window.inventoryStart                first slot of the inventory section
window.inventoryEnd                  one past its last slot (inventoryStart + 36)
window.hotbarStart                   inventoryEnd - 9: first hotbar slot
window.craftingResultSlot            slot number of the result slot, or -1 when none
window.requiresConfirmation          true for every window on 1.16.1
window.selectedItem                  Item | null: the stack on the mouse cursor
  The values per window type are in guide("window-types").

Reading the inventory section (inventoryStart to inventoryEnd - 1).
window.items() -> [Item]                               the items there, in slot order;
                                                       item.slot is a slot of this window
window.count(itemType, metadata) -> number             sum of count for that item id
window.emptySlotCount() -> number                      slots holding null
window.findInventoryItem(item, metadata, notFull) -> Item | null
window.firstEmptyInventorySlot(hotbarFirst = true) -> number | null
window.firstEmptyHotbarSlot() -> number | null         in hotbarStart to inventoryEnd - 1

Reading the container section (0 to inventoryStart - 1).
window.containerItems() -> [Item]                      the items there, in slot order
window.containerCount(itemType, metadata) -> number    sum of count for that item id
window.findContainerItem(item, metadata, notFull) -> Item | null
window.firstEmptyContainerSlot() -> number | null

Rules shared by the calls above.
  count and containerCount put itemType through parseInt(itemType, 10): a numeric id, or
  a string of digits, which is parsed; an item name gives 0. metadata null or undefined
  matches any item.
  findInventoryItem and findContainerItem take an item id (number) or an item name
  (string) and return the first match, lowest slot first; notFull true skips stacks
  whose count equals stackSize; any other type throws an AssertionError
  'No valid type given'.

Reading any range (start included, end not included).
window.itemsRange(start, end) -> [Item]
window.sumRange(start, end) -> number                  sum of count of all items
window.countRange(start, end, itemType, metadata) -> number
  itemType is compared with ===: a number only.
window.firstEmptySlotRange(start, end) -> number | null
window.lastEmptySlotRange(start, end) -> number | null
  Searches from end down to start, both included.
window.findItemRange(start, end, itemType, metadata, notFull, nbt,
                     withoutCraftResultSlot = false) -> Item | null
  First item with that id; metadata and nbt null or undefined match any; nbt is compared
  as JSON text; notFull true skips full stacks; withoutCraftResultSlot true skips the
  crafting result slot. itemType null throws an AssertionError.
window.findItemsRange(start, end, itemType, metadata, notFull, nbt,
                      withoutCraftResultSlot = false) -> [Item]     every such item
window.findItemRangeName(start, end, itemName, metadata, notFull) -> Item | null
  The same search by item name.
window.transactionRequiresConfirmation(click) -> boolean   returns requiresConfirmation
