guide("chunk-events"): columns loading and unloading, dimension change, waitForChunksToLoad.

A column is 16 x 16 blocks, y 0 to 255. Column (chunkX, chunkZ) holds the blocks with
floor(x / 16) = chunkX and floor(z / 16) = chunkZ.

Events on bot (and on bot.world).
'chunkColumnLoad' (corner)
  corner: Vec3(chunkX * 16, 0, chunkZ * 16). Emitted when
  - a chunk message of the server has been read into the column. That is every chunk
    message, also one for a column that is already loaded;
  - a light message arrives for a column that is not loaded: an empty column (air
    everywhere) is created and counts as loaded from then on. Its blocks arrive with the
    chunk message.
  A chunk message that cannot be read emits 'error' on bot and no 'chunkColumnLoad'.
'chunkColumnUnload' (corner)
  Emitted when the server's unload message for the column arrives (also for a column that
  was not loaded), when a chunk message says the column is empty, and for every loaded
  column when the dimension changes. After it, bot.blockAt in that column returns null.

Dimension change.
  bot.world is created at the first login message; before it bot.world is undefined. It
  stays the same object afterwards.
  A respawn message is a dimension change when its dimension differs from the current
  one; it is not when the dimension is the same, or when the world name is the same and
  the message says the player's data is kept. A respawn after death in the same
  dimension unloads nothing here.
  On a dimension change, in order:
  1. each 'blockUpdate:(x, y, z)' name with exactly one listener on bot: the listener is
     called with (null, null) and removed;
  2. every loaded column is unloaded, with 'chunkColumnUnload' for each.
  A later login message does the same two steps.
bot._getDimensionName() -> string
  The world name the server gave at the last login or dimension change, with
  'minecraft:' in front when the server's name lacks it: 'minecraft:overworld'.

bot.waitForChunksToLoad() -> Promise<void>
  1. If bot.entity.height is not set yet, it waits for one 'chunkColumnLoad', at most
     10000 ms; then it rejects 'Event chunkColumnLoad did not fire within timeout of
     10000ms'.
  2. It takes the 25 columns of the 5 x 5 square around the column of
     bot.entity.position (2 columns each way) and keeps those that are not loaded.
  3. None: resolves at once.
  4. Otherwise it resolves when a 'chunkColumnLoad' has come for each of them. After
     10000 ms it rejects 'Timeout waiting for <n> chunks to load after 10000ms', n being
     the number still missing.
  The square is fixed at step 2; the bot moving afterwards does not change it.
