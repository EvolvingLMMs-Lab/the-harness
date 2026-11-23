guide("block-object"): the fields of a Block object.

A Block is a snapshot. bot.blockAt, bot.findBlock, bot.world.getBlock, the rays and the
block events each build a new one. Writing a field changes only that object.

Identity.
block.type           number: the id of the kind of block (bot.registry.blocks[type])
block.name           string: 'stone', 'oak_log', 'air' ...
block.displayName    string: 'Stone', 'Oak Log' ...
block.stateId        number: the kind together with its state (facing, age, lit ...)
block.metadata       number: stateId minus the smallest stateId of the kind
block.position       Vec3 of whole numbers. null on a Block that was not read from a
                     position (the first test of bot.findBlocks, Block.fromStateId)

From the registry, the same for every block of the kind.
block.hardness       number, as the 1.16.1 game has it. 0: breaks at once. -1: cannot be
                     dug. Water and lava have 100.
block.diggable       boolean: hardness is not -1. false for: bedrock, moving_piston,
                     nether_portal, end_portal, end_portal_frame, end_gateway, barrier,
                     command_block, repeating_command_block, chain_command_block,
                     structure_block, jigsaw
block.boundingBox    'block' or 'empty'. 'empty': air, water, lava, plants, signs, torches
block.transparent    boolean
block.material       the kind of tool that digs the block faster, as the 1.16.1 game has
                     it (not Mineflayer's 'rock', 'wood', 'plant', ...). One of:
                     'pickaxe' (stone, ores, obsidian, furnace), 'axe' (logs, planks,
                     crafting_table, chest), 'shovel' (dirt, sand, gravel, clay),
                     'hoe' (hay_block, sponge), 'shears5' (wool), 'axe+sword1.5'
                     (melon, pumpkin, saplings, flowers), 'hoe+sword1.5+shears15'
                     (leaves), 'sword15+shears15' (cobweb), 'hand' (no tool is
                     faster: glass, beds, torches, water, lava). It is the key into
                     bot.registry.materials: guide("registry-materials")
block.harvestTools   { itemId: true, ... }: the items that make the block drop something.
                     undefined: every item and the bare hand do. stone and its like drop
                     nothing when dug with anything else, the bare hand included
To choose the item to dig a block with, compare the times: block.digTime(item.type, ...)
for each item in the inventory and for null (the bare hand), and take the shortest
(guide("dig-time")); do not read the kind of tool off block.material.
block.drops          array of item ids

From the state.
block.shapes         array of boxes [x0, y0, z0, x1, y1, z1], each from 0 to 1, measured
                     from the block's corner: the collision boxes of this state. [] when
                     nothing collides. A full cube is [[0, 0, 0, 1, 1, 1]]
block.missingStateShape  true when the registry has no shapes for this state; shapes is
                     then the one of the kind's first state. Otherwise not set
block.isWaterlogged  the 'waterlogged' property: true or false; undefined when the kind
                     has no such property

From the place.
block.light          number 0 to 15: block light there
block.skyLight       number 0 to 15: sky light there
block.biome          { id, name, category, temperature, precipitation, depth, dimension,
                     displayName, color, rainfall, child }
block.entity         the block entity's data as raw NBT, or undefined (chests, signs,
                     furnaces, spawners ... as far as the server has sent it)
block.blockEntity    the same data as a plain object, or undefined. Read only
block.painting       { id, position, name, direction } or undefined; set by bot.blockAt
                     with extraInfos true. name is a number on this version

Set by a ray (guide("raycast")).
block.face           number: the face the ray entered by. 0 bottom (-y), 1 top (+y),
                     2 north (-z), 3 south (+z), 4 west (-x), 5 east (+x)
block.intersect      Vec3: the point where the ray met the block

Only on blocks whose name contains 'sign' (guide("sign")).
block.getSignText(), block.setSignText(front), block.signText

A stateId the registry does not know gives: name '', displayName '', shapes [],
hardness 0, boundingBox 'empty', transparent true, diggable false.

block.computedStates is an empty object; block._properties holds what
block.getProperties() returns (the state as named properties, guide("block-methods"));
block.hash is not set on this version.
