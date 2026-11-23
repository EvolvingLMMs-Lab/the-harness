guide("registry-materials"): bot.registry.materials, the table of tool speeds.

bot.registry.materials
  An object keyed by a material name. Each value is an object keyed by item id; the
  number is the digging speed of that item on blocks of that material.
  bot.registry.materials.pickaxe -> { 573: 6, 589: 2, 593: 4, 597: 8, 604: 12, 608: 9 }
  The body takes this table from the 1.16.1 game itself: a material is the kind of tool
  the game gives a speed on the block. Mineflayer's own names ('rock', 'wood', 'plant',
  'dirt', 'web', 'wool') are not in it.

The whole table (item names in place of ids).
  pickaxe                 wooden_pickaxe 2, stone_pickaxe 4, iron_pickaxe 6,
                          diamond_pickaxe 8, netherite_pickaxe 9, golden_pickaxe 12
  axe                     the six axes with the same numbers
  shovel                  the six shovels with the same numbers
  hoe                     the six hoes with the same numbers
  axe+sword1.5            the six axes with those numbers; each of the six swords 1.5
  hoe+sword1.5+shears15   the six hoes with those numbers; each sword 1.5; shears 15
  sword15+shears15        each of the six swords 15; shears 15
  shears5                 shears 5
  hand                    empty: no item is faster than the bare hand

Which blocks have which material.
  A block record's material field names the entry: guide("registry-blocks"). Every block
  has one.
  pickaxe 289 blocks (stone, ores, obsidian, furnace, rails), axe 176 (logs, planks,
  crafting_table, chest, doors), hand 177 (air, glass, beds, torches, water, lava),
  axe+sword1.5 59 (melon, pumpkin, saplings, flowers, grass), shovel 31 (dirt, sand,
  gravel, clay), shears5 16 (wool), hoe 8 (hay_block, sponge, nether_wart_block),
  hoe+sword1.5+shears15 6 (the leaves), sword15+shears15 1 (cobweb).

How the speed of a tool is read.
  speed = bot.registry.materials[block.material][heldItemId]
  When the entry does not hold the item in the hand, the speed is 1 (the speed of an
  empty hand).
  block.digTime and bot.digTime start from this number and then apply enchantments,
  effects, water and being in the air.

  const block = bot.blockAt(point)
  const speeds = bot.registry.materials[block.material] || {}
  const pick = bot.registry.itemsByName.iron_pickaxe.id
  speeds[pick]                             6 on stone, undefined on dirt

Speed and harvest are two tables.
  materials gives the speed. A block record's harvestTools gives the items with which
  block.canHarvest is true, and so the block drops something: stone lists all six
  pickaxes, iron_ore the stone, iron, diamond and netherite pickaxe, obsidian the diamond
  and the netherite pickaxe. 262 blocks have harvestTools; the other 501 drop with
  anything.
