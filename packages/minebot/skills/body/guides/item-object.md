guide("item-object"): the Item object: its plain fields, durability, and how one is made.

An Item is one stack in one slot. The entries of window.slots, bot.heldItem and the
results of window.items() are Item objects or null. The fields read from nbt (enchants,
names, repair cost) and the static functions are in guide("item-nbt-and-static").

item.type                            number: the item id (bot.registry.items[type])
item.count                           number: how many are in the stack
item.metadata                        number: 0 for every item the server sends on 1.16.1
item.nbt                             the item's NBT compound as sent by the server, in the
  prismarine-nbt form { type: 'compound', name: '', value: { ... } }, or null when the
  item has none.
item.name                            string: the item name, for example 'diamond_pickaxe'
item.displayName                     string: the English name, for example 'Diamond Pickaxe'
item.stackSize                       number: the largest count of one stack (64, 16 or 1)
item.maxDurability                   number for items that wear out; undefined for others
item.slot                            number: the slot it sits in
  Written by window.updateSlot each time the item is put in a slot. It is the slot number
  in the window that last stored it: for an item read from bot.currentWindow it is that
  window's numbering, not bot.inventory's. An Item that was not yet put in a window has
  no slot field.
item.stackId                         null on 1.16.1
  An id that is not in bot.registry.items gives name 'unknown', displayName 'unknown',
  stackSize 1.

item.durabilityUsed                  getter and setter
  Reading: the number in nbt Damage (how much durability is used up). When nbt has no
  Damage: 0 for an item with maxDurability, null for an item without.
  Remaining uses are item.maxDurability - item.durabilityUsed.
  Writing a number stores it as an int in nbt Damage (nbt is created when null). It
  changes the local object only.

new Item(type, count, metadata, nbt, stackId, sentByServer)
  The class is require('prismarine-item')(bot.registry).
  type null or undefined gives an object with no fields at all.
  When metadata is an object, it is taken as nbt and metadata becomes 0.
  metadata null or undefined becomes 0; nbt falsy becomes null.
  name, displayName, stackSize and maxDurability are copied from bot.registry.items[type].
  When sentByServer is falsy and the item has maxDurability and no used durability, the
  constructor writes durabilityUsed = 0, which creates nbt with Damage 0.
  Items built from server packets arrive through Item.fromNotch.

Fields are plain and writable. Writing item.count or any other field changes only the
local object; nothing is sent to the server. The local window code itself changes
item.count when a confirmed click moves part of a stack.
