guide("enchant-table"): bot.openEnchantmentTable: the window, its options, 'ready'.

bot.openEnchantmentTable(enchantmentTableBlock) -> Promise<enchantmentTable>
  1. enchantmentTableBlock.name is not 'enchanting_table': rejects with an AssertionError.
     Nothing is sent.
  2. Calls bot.openBlock(block): the bot turns its head to the centre of the block, sends
     one use-block packet on its top face, and waits for the bot event 'windowOpen',
     20 seconds at most ('Event windowOpen did not fire within timeout of 20000ms'). The
     code checks no distance.
  3. The window's type does not start with 'minecraft:enchant': rejects with
     'Expected minecraft:enchant when opening table but got ' followed by the type; that
     window stays open.
  4. Sets xpseed to -1 and the three options to unknown (below), adds the methods, and
     resolves with the enchantment table window (mineflayer.EnchantmentTable). It does
     not wait for 'ready'.

Slots of the window.
  0 the item to enchant, 1 lapis lazuli, 2 to 37 the bot's inventory (29 to 37 the
  hotbar). Slot s of bot.inventory (9 to 44) is slot s - 7 of this window.

enchantmentTable.targetItem() -> Item | null     enchantmentTable.slots[0]

enchantmentTable.enchantments      array of 3 options, index 0 to 2:
  { level, expected: { enchant, level } }
  level             the experience level the option requires, as the server sent it;
                    -1: not received yet
  expected.enchant  the numeric id of one enchantment the option gives; -1: not received
  expected.level    the level of that enchantment; -1: not received
enchantmentTable.xpseed            the seed number the server sent; -1: not received

How they update.
  The server sends window property packets for the open table; each carries one property
  number and one value:
    0, 1, 2    enchantments[0..2].level
    3          xpseed
    4, 5, 6    enchantments[0..2].expected.enchant
    7, 8, 9    enchantments[0..2].expected.level
  A packet for another window id is ignored. Each packet overwrites the one value it
  names.

enchantmentTable 'ready' event     no arguments
  After each of these packets the code looks at the three level values. All three 0 or
  more: 'ready' is emitted, unless the table is already in the ready state. One of them
  below 0: the ready state is cleared, and the next time all three are 0 or more 'ready'
  is emitted again.
  The code does not compare any level with bot.experience.level and does not look at the
  lapis slot.

The packet listener is removed when the window emits 'close'; enchantmentTable.close()
emits it.

Putting the item and the lapis in, enchanting, taking the item: guide("enchant-use").
