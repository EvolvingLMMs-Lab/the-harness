guide("inventory-read"): bot.inventory, its slot numbers, and the calls that read it.

bot.inventory                        a Window object: the bot's own inventory window
  id 0, type 'minecraft:inventory', title 'Inventory', 46 slots. It exists from the start
  and is the same object for the whole session. Its fields and every method are in
  guide("window-object"). What changes it is in guide("inventory-updates").

Slot numbers of bot.inventory.
  0        result of the 2 by 2 crafting grid (bot.inventory.craftingResultSlot is 0)
  1 to 4   the 2 by 2 crafting grid
  5        head        6  torso        7  legs        8  feet
  9 to 35  the 27 main slots
  36 to 44 the 9 hotbar slots (36 is hotbar slot 0)
  45       off hand
  bot.inventory.inventoryStart is 9, bot.inventory.inventoryEnd is 45 (not included),
  bot.inventory.hotbarStart is 36. bot.QUICK_BAR_START is 36.

bot.inventory.slots                  array of 46 entries (Item or null), by slot number
bot.inventory.selectedItem           the Item on the mouse cursor of this window, or null

bot.inventory.items() -> [Item]
  The items in slots 9 to 44, in slot order. Slots 0 to 8 (crafting, armour) and slot 45
  (off hand) are not in it. Each Item is the same object that sits in bot.inventory.slots.
  The Item fields are in guide("item-object").

bot.inventory.count(itemType, metadata) -> number
  Adds up item.count over slots 9 to 44 for items whose type equals itemType. itemType
  goes through parseInt(itemType, 10): a number or a string of digits works, an item name
  gives NaN and the result 0. metadata null or undefined matches every item; on 1.16.1
  every item has metadata 0.

bot.inventory.emptySlotCount() -> number
  The number of slots from 9 to 44 that hold null.

bot.inventory.findInventoryItem(item, metadata, notFull) -> Item | null
  item is an item id (number) or an item name (string). Returns the first match in slots
  9 to 44, lowest slot first, or null. metadata null or undefined matches every item.
  notFull true skips stacks whose count equals stackSize. Any other type of item (an
  object, null) throws an AssertionError 'No valid type given'; undefined returns null.

bot.inventory.firstEmptyInventorySlot(hotbarFirst = true) -> number | null
  hotbarFirst true: the first empty slot in 36 to 44; when the hotbar is full, or with
  hotbarFirst false, the first empty slot in 9 to 44. null when there is none.
bot.inventory.firstEmptyHotbarSlot() -> number | null     first empty slot in 36 to 44

bot.heldItem                         the Item in the selected hotbar slot, or null
bot.entity.equipment                 [hand, off hand, feet, legs, torso, head]
  A getter defined at each 'spawn' event. It returns [bot.heldItem, slots[45], slots[8],
  slots[7], slots[6], slots[5]] of bot.inventory; each entry is an Item or null.

bot.registry.itemsByName.NAME.id     the numeric id of an item name
bot.registry.items[id]               { id, name, displayName, stackSize }, and
                                     maxDurability for items that wear out
