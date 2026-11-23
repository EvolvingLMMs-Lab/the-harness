guide("world-columns"): the column objects in bot.world, and bot.world.async.

The column object (from bot.world.getColumn, getColumnAt, getColumns).
  It holds one column: 16 x 16 blocks, y 0 to 255. Its calls take a position inside the
  column: a Vec3 with x and z from 0 to 15 and y the world height; whole numbers. They
  emit no event.
  column.getBlock(p) -> Block          position is not set on it (null)
  column.getBlockStateId(p), column.getBlockType(p), column.getBlockLight(p),
  column.getSkyLight(p), column.getBiome(p) -> number
  column.setBlock(p, block), column.setBlockStateId(p, stateId),
  column.setBlockType(p, type), column.setBlockLight(p, light),
  column.setSkyLight(p, light), column.setBiome(p, biomeId)
  column.sections      array of 16 sections of 16 blocks height (index floor(y / 16)); an
                       entry is null when the section holds nothing. section.palette is
                       the list of the stateIds the section uses, or null
  A y outside 0 to 255 reads as air.

bot.world.async
  The same world with calls that return promises. It shares the columns with bot.world:
  a read gives the same data.
  bot.world.async.columns                 object { 'chunkX,chunkZ': column }
  bot.world.async.getLoadedColumn(chunkX, chunkZ), getLoadedColumnAt(pos)
                                          the column or undefined, at once
  await bot.world.async.getColumn(chunkX, chunkZ), getColumnAt(pos)
                                          the column or undefined
  await bot.world.async.getBlock(pos), getBlockStateId(pos), getBlockType(pos),
  getBlockData(pos), getBlockLight(pos), getSkyLight(pos), getBiome(pos)
    The same values as on bot.world. In a column that is not loaded they reject with a
    TypeError (bot.world returns null or 0 there).
  await bot.world.async.setBlock(pos, block), setBlockStateId, setBlockType,
  setBlockData, setBlockLight, setSkyLight, setBiome
    They write the shared columns and emit 'blockUpdate' and `blockUpdate:${pos}` on
    bot.world.async only: listeners on bot and on bot.world are not called. In a column
    that is not loaded they reject with a TypeError.
  await bot.world.async.raycast(from, direction, range, matcher = null)
    As bot.world.raycast without matcher. With matcher, matcher(block) selects which
    blocks are tested; the shapes are still tested and face and intersect are set. It
    rejects when the ray enters a column that is not loaded.
  bot.world.async.setLoadedColumn(chunkX, chunkZ, column, save = true),
  await setColumn(...), unloadColumn(chunkX, chunkZ)
    They change the shared columns and emit 'chunkColumnLoad' / 'chunkColumnUnload' on
    bot.world.async only.
  Saving (saveNow, startSaving, stopSaving, waitSaving, queueSaving, saveAt, savingQueue,
  unloadQueue, finishedSaving, storageProvider, savingInterval, chunkGenerator): the
  world has no generator. It has a storage provider only when the bot was created with
  the storageBuilder option; without it storageProvider is null, nothing is saved,
  saveAt does nothing, and saveNow and waitSaving resolve at once.
  bot.world.async.sync is bot.world.
