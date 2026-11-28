guide("world-object"): bot.world: direct reads and writes of the bot's copy of the world.

bot.world is the bot's copy of the loaded columns. Every call here returns at once (no
promise). pos is a Vec3 in world coordinates; fractions are floored. Writes change the
bot's copy only: nothing is sent to the server, and the next message of the server for
that block or column overwrites them.

Reads. In a column that is not loaded getBlock returns null and the others return 0.
bot.world.getBlock(pos) -> Block | null      what bot.blockAt returns, without painting
bot.world.getBlockStateId(pos) -> number     block.stateId without building a Block
bot.world.getBlockType(pos) -> number        block.type
bot.world.getBlockData(pos) -> undefined     has no value on this version
bot.world.getBlockLight(pos) -> number       0 to 15
bot.world.getSkyLight(pos) -> number         0 to 15
bot.world.getBiome(pos) -> number            the biome id
bot.world.raycast(from, direction, range, matcher)       guide("raycast")

Writes. Each reads the old block, writes, then emits 'blockUpdate' (oldBlock, newBlock)
and `blockUpdate:${pos}` (oldBlock, newBlock) on bot.world; the first is passed on to
bot. The name of the second is built from pos as given: a pos with fractions gives a name
with fractions. In a column that is not loaded they do nothing.
bot.world.setBlockStateId(pos, stateId)
bot.world.setBlockType(pos, type)        the first state of that kind of block
bot.world.setBlockData(pos, data)        the kind that is there, in its state number data
                                         (stateId = the kind's smallest stateId + data)
bot.world.setBlockLight(pos, light)
bot.world.setSkyLight(pos, light)
bot.world.setBiome(pos, biomeId)
bot.world.setBlock(pos, block)
  Writes block.stateId, block.biome.id, block.skyLight, block.light and block.entity (no
  entity: the block entity there is removed). newBlock in the events is the object given.

Columns.
bot.world.getColumn(chunkX, chunkZ) -> column | undefined
bot.world.getColumnAt(pos) -> column | undefined
  The column holding pos: chunkX = floor(pos.x / 16), chunkZ = floor(pos.z / 16).
  undefined when not loaded.
bot.world.getColumns() -> [{ chunkX, chunkZ, column }]
  Every loaded column. chunkX and chunkZ are strings here ('-3').
bot.world.setColumn(chunkX, chunkZ, column, save = true)
  Puts a column object in place and emits 'chunkColumnLoad'.
bot.world.unloadColumn(chunkX, chunkZ)
  Removes the column and emits 'chunkColumnUnload'.
bot.world.initialize(iniFunc, length, width, height = 256, iniPos = new Vec3(0, 0, 0))
  Fills a box of blocks from iniFunc(x, y, z) -> Block | null in the columns it touches.
  Each of those columns has to be loaded: an unloaded one throws a TypeError.
The column object and bot.world.async: guide("world-columns").

Events on bot.world.
  'blockUpdate' (oldBlock, newBlock), `blockUpdate:(x, y, z)` (oldBlock, newBlock),
  'chunkColumnLoad' (corner), 'chunkColumnUnload' (corner). bot emits the same ones:
  guide("block-events"), guide("chunk-events"). A listener put on bot.world with once is
  removed after its first call.
