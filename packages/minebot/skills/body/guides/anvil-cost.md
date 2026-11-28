guide("anvil-cost"): how the level cost of an anvil operation is computed (Item.anvil).

Item.anvil(itemOne, itemTwo, creative, renamedName) -> { xpCost, item, usedMats }
  Item is require('prismarine-item')(bot.registry). It computes locally, sends nothing.
  itemOne: the item in the first slot. itemTwo: the item in the second slot, or null.
  xpCost: the cost in experience levels; 0 means the operation is not possible.
  item: the expected result Item, or null. usedMats: repair materials used.
  anvil.combine and anvil.rename use only xpCost.

xpCost is 0 at once when
  itemTwo is not null and its name is none of: itemOne's name, one of itemOne's repair
  materials (bot.registry.itemsByName.NAME.repairWith), 'enchanted_book' (for an itemOne
  that is not an enchanted book).

Else the cost is the sum of:
  Rename: +1 when renamedName is a string. (xpCost is 0 at once when itemOne's nbt
    RepairCost is 2147483647.)
  Repair, when itemOne.durabilityUsed is not 0:
    itemTwo null or an enchanted book: +0.
    itemTwo has the same name as itemOne: +2.
    itemTwo is a repair material: one material restores floor(maxDurability * 0.25)
      durability; needed = ceil(durabilityUsed / that). itemTwo.count above needed:
      +needed. Else: +itemTwo.count.
  Enchantments, when itemTwo has the same name as itemOne or is an enchanted book: for
  each enchantment on itemTwo:
    multiplier by the enchantment's weight: weight 10: 1, 5: 2, 2: 4, 1: 8; from a book
      half of that, at least 1.
    outside creative, an enchantment whose category is not one of itemOne's
      enchantCategories is skipped (not for book on book).
    itemOne does not have it: +1 when it excludes an enchantment itemOne has; else
      + its level * multiplier.
    itemOne has it: final level = level + 1 for equal levels (at most the enchantment's
      maxLevel), else the higher of the two; + final level * multiplier.
    When this enchantment sum is 0 and there is no rename: xpCost is 0.
  Prior work: + itemOne.repairCost + itemTwo.repairCost (the RepairCost value of each
    item's nbt, 0 when absent).

Then
  itemTwo null and itemOne.customName equals renamedName: xpCost is 0.
  The sum is above 39, renamedName is a string, itemOne.durabilityUsed is 0 and the
    enchantment step did not run: xpCost is 39.
  Else the sum is 40 or more: xpCost is 0.

Two items of the same name, damaged or not, with no enchantment on itemTwo and no rename
give xpCost 0 in both orders.
itemOne.durabilityUsed is 0 for an undamaged item that has durability, and null for an
item without durability.
