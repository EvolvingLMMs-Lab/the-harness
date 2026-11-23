guide("registry-biomes-and-windows"): the biome and window records of bot.registry.

bot.registry.biomes[id], bot.registry.biomesByName[name], bot.registry.biomesArray
  79 records on 1.16.1. The ids are not continuous: 0 to 50, 127, 129 to 134, 140, 149,
  151, 155 to 158, 160 to 173.
  { id: 1, name: 'plains', category: 'plains', temperature: 0.8, precipitation: 'rain',
    depth: 0.125, dimension: 'overworld', displayName: 'Plains', color: 9286496,
    rainfall: 0.4, child: 129 }

Biome fields.
id             number, the biome id stored in the world (block.biome.id)
name           string: 'plains', 'desert', 'nether_wastes', 'the_end', 'soul_sand_valley'
displayName    string
category       'ocean', 'plains', 'desert', 'extreme_hills', 'forest', 'taiga', 'swamp',
               'river', 'nether', 'the_end', 'icy', 'mushroom', 'beach', 'jungle',
               'savanna', 'mesa' or 'none'
dimension      'overworld', 'nether' or 'end'
temperature    number (plains 0.8, desert 2, snowy_tundra 0)
precipitation  'rain', 'snow' or 'none'
rainfall       number, 0 to 1
depth          number, the base height of the terrain (ocean -1, plains 0.125)
color          number, a colour as one integer
child          on 21 records: the id of the variant biome (plains: 129)
parent         on 21 records: the name of the base biome (sunflower_plains: 'plains')
climates       on the 5 nether biomes: [{ temperature, humidity, altitude, weirdness,
               offset }]
Ids: 0 ocean, 1 plains, 2 desert, 3 mountains, 4 forest, 5 taiga, 6 swamp, 7 river,
  8 nether_wastes, 9 the_end, 14 mushroom_fields, 16 beach, 21 jungle, 24 deep_ocean,
  27 birch_forest, 29 dark_forest, 35 savanna, 37 badlands, 127 the_void,
  170 soul_sand_valley, 171 crimson_forest, 172 warped_forest, 173 basalt_deltas.
  bot.registry.biomesArray.map(b => b.id + ' ' + b.name) lists all 79.

bot.registry.windows[typeString], bot.registry.windowsByName[name],
bot.registry.windowsArray
  14 records. As typeString name:
    '' Player, 'EntityHorse' Horse, 'minecraft:anvil' Anvil, 'minecraft:beacon' Beacon,
    'minecraft:brewing_stand' Brewing Stand, 'minecraft:chest' Chest,
    'minecraft:container' Container, 'minecraft:crafting_table' Workbench,
    'minecraft:dispenser' Dispenser, 'minecraft:dropper' Dropper,
    'minecraft:enchanting_table' Enchantment Table, 'minecraft:furnace' Furnace,
    'minecraft:hopper' Hopper, 'minecraft:villager' NPC Trade

Window fields.
id             the type string above
name           the display name above
slots          on 9 records: array of { name, index, size }. index is the first slot
               number, size the number of slots (absent: 1)
                 Player: craft result 0; craft grid 1, size 4; armor 5, size 4;
                   helmet 5; chestplate 6; leggings 7; boots 8
                 Workbench: craft result 0; craft grid 1, size 9
                 Furnace: smelted 0; fuel 1; result 2
                 Anvil: tool 0; combined 1; result 2
                 Enchantment Table: enchanted 0; lapis 1
                 Brewing Stand: ingredient 0; result 1, size 3
                 Beacon: input 0
                 NPC Trade: give 1 at 0; give 2 at 1; take 2
                 Horse: saddle 0; armor 1; storage 2, size 15
properties     on 5 records: the names of the window's numeric properties, in order
                 Furnace: fuel, fuel max, progress, progress max
                 Enchantment Table: xp 1, xp 2, xp 3, seed, tooltip 1, tooltip 2,
                   tooltip 3
                 Anvil: repair cost. Brewing Stand: brew time.
                 Beacon: level, effect 1, effect 2
openedWith     on 3 records (Horse, Beacon, Brewing Stand): [{ type: 'block' or
               'entity', id }]
bot.openContainer, bot.openFurnace and the other window calls do not read these records.
