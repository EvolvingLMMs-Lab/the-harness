guide("registry-loot"): bot.registry.blockLoot and entityLoot, the drop tables.

bot.registry.blockLoot[blockName] -> { block, drops }
bot.registry.blockLootArray              the 701 records
  Keyed by the block's name. 62 of the 763 blocks have no record (undefined): air,
  bedrock, water, lava, the wall forms of torches, signs, heads, banners and coral fans,
  portals, command blocks, barrier, piston_head, moving_piston, bubble_column, jigsaw,
  structure blocks.
  block    the block's name
  drops    array of drop entries (below); [] for cake, fire, soul_fire, frosted_ice,
           nether_portal, spawner

bot.registry.entityLoot[entityName] -> { entity, drops }
bot.registry.entityLootArray             the 71 records
  Keyed by the entity's name. 36 of the 107 entities have no record (undefined):
  projectiles, vehicles, dropped items and the like.
  drops is [] for: armor_stand, bat, bee, ender_dragon, endermite, fox, giant,
  illusioner, ocelot, piglin, pillager, player, silverfish, vex, villager,
  wandering_trader, wither, wolf.

A drop entry.
  item             the NAME of the item (a string, not an id)
  dropChance       a number from 0 to 1
  stackSizeRange   [min, max] items of that entry
  silkTouch        true: the entry applies with Silk Touch (block entries only)
  noSilkTouch      true: the entry applies without Silk Touch (block entries only)
  blockAge         a number: the entry applies at that age of the crop (block entries
                   only: 7 for wheat, carrots, potatoes; 3 for beetroots; 2 and 3 for
                   sweet_berry_bush)
  playerKill       true: the entry applies when a player made the kill (entity entries
                   only)
  An entry holds only the flags that are set.

Block records.
  stone        [{ item: 'stone', dropChance: 0.5, stackSizeRange: [1, 1], silkTouch:
               true }, { item: 'cobblestone', dropChance: 0.5, stackSizeRange: [1, 1],
               noSilkTouch: true }]
  diamond_ore  diamond_ore (silkTouch), diamond [1, 2] (noSilkTouch)
  coal_ore     coal_ore (silkTouch), coal [1, 2] (noSilkTouch)
  iron_ore     iron_ore, dropChance 1
  oak_log      oak_log, dropChance 1
  glass        glass (silkTouch); no entry without it
  gravel       gravel (silkTouch), flint (noSilkTouch), gravel (noSilkTouch), each 1/3
  grass_block  grass_block (silkTouch), dirt (noSilkTouch)
  oak_leaves   oak_leaves 0.5, oak_sapling 0.5, stick 1, apple 1
  wheat        wheat 0.5 (blockAge 7), wheat_seeds 0.5, wheat_seeds 1 [1, 4] (blockAge 7)
  carrots      carrot 1, carrot 1 [1, 4] (blockAge 7)

Entity records.
  zombie       rotten_flesh 1; iron_ingot, carrot, potato each 0.00833 (playerKill)
  skeleton     arrow 1, bone 1
  spider       string 1, spider_eye 1 (playerKill)
  cow          leather 1, beef 1
  chicken      feather 1, chicken 1
  pig          porkchop 1
  sheep        mutton 1 (the record has no wool entry)
  enderman     ender_pearl 1
  blaze        blaze_rod 1 (playerKill)
  Every stackSizeRange above without brackets is [1, 1].

dropChance and stackSizeRange are the numbers of the table. In the stone record the two
entries, one for each case of Silk Touch, carry 0.5 each.

A block record's drops field (item ids) lists the same items without the conditions.
