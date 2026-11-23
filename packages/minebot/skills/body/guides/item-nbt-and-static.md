guide("item-nbt-and-static"): Item fields read from NBT (enchantments, names, repair
cost) and the static functions of the Item class.

Each setter below changes the local Item object only; nothing is sent to the server.

item.enchants                        getter -> [{ name, lvl }]
  name is the enchantment name without 'minecraft:' (for example 'efficiency'), or null
  when the stored id is not a string; lvl is the level number. [] when there are none.
  For an item named 'enchanted_book' it reads the nbt list StoredEnchantments when that
  exists, otherwise Enchantments. For every other item it reads Enchantments.
item.enchants = [{ name, lvl }]      setter
  Writes the list to nbt (StoredEnchantments for 'enchanted_book', Enchantments for
  others); nbt is created when null. A name that is not in bot.registry.enchantmentsByName
  throws a TypeError. Assigning [] leaves the nbt as it was.

item.customName                      getter: the string in nbt display.Name, or null
  The string is what the server stored, unchanged. The setter writes a string there.
item.customLore                      getter: nbt display.Lore simplified, or null
  null when the item has no nbt display. The setter writes its value as one NBT string.
item.repairCost                      getter: the number in nbt RepairCost, or 0
  The setter writes an int there.
item.customModel                     getter only: nbt CustomModelData, or null
item.blocksCanPlaceOn                getter: [[name], ...] from the nbt list CanPlaceOn
item.blocksCanDestroy                getter: [[name], ...] from the nbt list CanDestroy
  Both give [] when the list is absent. Their setters take an array of block names, add
  'minecraft:' to names without a namespace, and write the list; [] deletes the list.
item.spawnEggMobName                 getter: item.name with '_spawn_egg' removed
  For 'pig_spawn_egg' it gives 'pig'. For any other item it gives item.name unchanged.

Static functions (Item is require('prismarine-item')(bot.registry)).

Item.equal(item1, item2, matchStackSize = true, matchNbt = true) -> boolean
  Both null or undefined: true. One of them null or undefined: false. Otherwise true when
  type and metadata are equal, and count is equal (skipped with matchStackSize false),
  and JSON.stringify of the two nbt values is equal (skipped with matchNbt false).

Item.toNotch(item) -> object
  The packet form. null or undefined gives { present: false }. An item gives
  { present: true, itemId: item.type, itemCount: item.count, nbtData: item.nbt }; nbtData
  is undefined when nbt is null or has no keys.
Item.fromNotch(networkItem) -> Item | null
  null when networkItem.present is false. Otherwise a new Item with type itemId, count
  itemCount, metadata 0, nbt nbtData (or null).

Item.anvil(itemOne, itemTwo, creative, renamedName) -> { xpCost, item, usedMats }
  Computes locally what an anvil gives for itemOne (left) and itemTwo (right, or null),
  with renamedName a string or undefined. It sends nothing.
  It returns { xpCost: 0, item: null } when: itemTwo is not null and is neither the same
  item, nor one of itemOne's repair materials, nor an 'enchanted_book'; the rename is
  impossible (RepairCost 2147483647); nothing would change; or the cost is 40 or more
  (a pure rename is capped at 39 instead).
  Cost: 1 for a rename; repair with the same item 2; repair with material 1 per material
  used (each restores a quarter of maxDurability); for each enchantment taken from
  itemTwo, final level times a multiplier (by enchantment weight 10, 5, 2, 1: 1, 2, 4, 8;
  halved, at least 1, when itemTwo is a book); plus 1 for each enchantment that excludes
  one already present; plus both items' repairCost.
  item is a new Item with the merged enchantments, the name, the new durabilityUsed, and
  repairCost = 2 * max(both repairCost) + 1.

Item.currentStackId, Item.nextStackId()   a counter used on Bedrock only; unused on 1.16.1
