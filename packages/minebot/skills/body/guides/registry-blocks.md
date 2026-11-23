guide("registry-blocks"): the block records of bot.registry: every field and its values.

bot.registry.blocks[id], bot.registry.blocksByName[name], bot.registry.blocksArray
  763 records on 1.16.1, ids 0 to 762. A block id is not an item id: stone is block 1
  and item 1, but diamond_ore is block 149 and item 181. 102 blocks have no item of the
  same name (air, water, lava, wall_torch, ...). The block 'wheat' (152) is the crop;
  the item 'wheat' (620) is the harvested wheat.

One record, bot.registry.blocksByName.diamond_ore:
  { id: 149, name: 'diamond_ore', displayName: 'Diamond Ore', hardness: 3,
    resistance: 3, stackSize: 64, diggable: true, material: 'pickaxe', transparent: false,
    emitLight: 0, filterLight: 15, boundingBox: 'block', minStateId: 3354,
    maxStateId: 3354, defaultState: 3354, states: [], drops: [181, 581],
    harvestTools: { 573: true, 597: true, 608: true } }
  (hardness, diggable, material and harvestTools are the 1.16.1 game's own values: the
  body puts them in place of Mineflayer's.)

Fields.
id             number, the block type id
name           string, for example 'oak_log'
displayName    string, for example 'Oak Log'
hardness       number, read by block.digTime. 0 for 145 blocks (torch, grass, air,
               saplings, ...); 100 for water and lava; 50 for obsidian; 1.5 for stone;
               0.5 for dirt; -1 for the 12 blocks that cannot be dug
resistance     number, the blast resistance (stone 6, obsidian 1200, bedrock 3600000)
stackSize      0 for 15 blocks (air, water, lava, sand, red_sand, fire, soul_fire,
               nether_portal, end_portal, end_gateway, frosted_ice, void_air, cave_air,
               bubble_column, chiseled_polished_blackstone); 1 for beds, cake, shulker
               boxes and campfires; 16 for signs and banners; 64 for the rest. The
               stack size an inventory uses is the one of the item record
diggable       boolean: hardness is not -1. false for: bedrock, moving_piston,
               nether_portal, end_portal, end_portal_frame, command_block,
               repeating_command_block, chain_command_block, barrier, end_gateway,
               structure_block, jigsaw
material       string, on every block: the kind of tool the game gives a speed on it.
               'pickaxe' (289 blocks), 'hand' (177: no tool is faster), 'axe' (176),
               'axe+sword1.5' (59), 'shovel' (31), 'shears5' (16), 'hoe' (8),
               'hoe+sword1.5+shears15' (the 6 leaves), 'sword15+shears15' (cobweb).
               It is the key into bot.registry.materials:
               guide("registry-materials")
harvestTools   object { itemId: true }, on 262 blocks; absent on 501. Present:
               block.canHarvest is true only with one of these items in the hand,
               and the block drops nothing when dug with anything else. Absent:
               canHarvest is true with anything. stone lists the six pickaxes;
               diamond_ore the iron, diamond and netherite pickaxe; obsidian the
               diamond and the netherite pickaxe
drops          array of item ids the block can give (stone: [1, 14], stone and
               cobblestone). It does not say which drop comes with which tool:
               guide("registry-loot")
transparent    boolean; true for 488 blocks
emitLight      0 to 15, the light the block gives off; above 0 for 22 blocks
filterLight    the light the block takes away: 0, 15, or 2 (water, frosted_ice)
boundingBox    'block' (579 blocks) or 'empty' (184 blocks: air, liquids, saplings,
               flowers, torches, signs, rails, cobweb, wheat, ...). 'empty': the block
               has no collision box in any of its states. 'block': it has one in at
               least one state (full blocks, and also slabs, fences, doors)
minStateId, maxStateId, defaultState, states
               the block's range of state ids and its properties:
               guide("registry-block-states")
