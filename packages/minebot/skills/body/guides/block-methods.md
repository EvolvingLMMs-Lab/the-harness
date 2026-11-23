guide("block-methods"): the methods of a Block object and the ways to build one.

block.getProperties() -> object
  The state of the block as named properties, for example for a chest
  { waterlogged: false, type: 'single', facing: 'north' }, for wheat { age: 0 }.
  A boolean property gives true or false. A number property that starts at 0 (age,
  level, bites, moisture, rotation) gives a number. Every other property gives a string;
  that includes the number properties that start at 1: layers of snow gives '1',
  distance of leaves '7', delay of a repeater '1'.
  The result is the block's own object, the same one on every call.
  A kind without states gives {}.

block.canHarvest(heldItemType) -> truthy | falsy
  heldItemType: an item id, or null for the bare hand.
  block.harvestTools undefined: true.
  Otherwise: true when harvestTools has that item id; with null it returns null.
  It reads nothing but harvestTools.

block.digTime(heldItemType, creative, inWater, notOnGround, enchantments = [],
              effects = {}) -> number of milliseconds
  The time bot.dig waits. Every step of the count: guide("dig-time").

block.blockEntity                  getter: block.entity as a plain object, or undefined

Building a Block. The class is require('prismarine-block')(bot.registry).
Block.fromStateId(stateId, biomeId) -> Block
  The block of that stateId. position is null, light and skyLight are 0.
Block.fromProperties(typeId, properties, biomeId) -> Block
  typeId: a block id or a block name. properties: { name: value }.
  A property that is not given takes its first value in the registry (for a boolean
  that is true). A property name the kind does not have is ignored.
  Throws 'No matching block id found for <typeId> with properties <json>' for an unknown
  typeId.
Block.fromString(str, biomeId) -> Block
  str: 'minecraft:oak_stairs[facing=east,half=top]' (the 'minecraft:' is optional). It
  calls Block.fromProperties with the name and the listed properties.
new Block(type, biomeId, metadata, stateId)
  With stateId undefined the stateId is the kind's smallest stateId plus metadata, capped
  at the kind's largest.
Block.getHash(name, states)        returns undefined on this version

A Block built this way is not in the world. bot.world.setBlock(pos, block) writes it into
the bot's copy only (guide("world-object")).
