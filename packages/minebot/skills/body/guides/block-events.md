guide("block-events"): the block update events and what changes the bot's copy of blocks.

Events on bot.
'blockUpdate' (oldBlock, newBlock)
  A block in the bot's copy of the world was written. Both are Block objects with
  position set; oldBlock was read just before the write, newBlock just after. The two can
  be equal in every field (a write of the same state emits too).

'blockUpdate:(x, y, z)' (oldBlock, newBlock)
  The same, for one position. The name has whole numbers and one space after each comma:
  `blockUpdate:${block.position}` gives it.
  A listener added on bot under such a name is attached to bot.world; bot.world calls it.
  bot.off / bot.removeListener with the same function detaches it. bot.once does not
  detach it after the first call: the function runs on every update of the position
  until it is removed.
  When the dimension changes, each such name that has exactly one listener on bot gets
  one call with (null, null), and that listener is removed.

'blockPlaced' (oldBlock, newBlock)       emitted by bot.placeBlock
'diggingCompleted' (block), 'diggingAborted' (block)       emitted by bot.dig
'blockEntityData' (block)
  The server sent the data of one block entity (a sign's text, a spawner, a chest ...).
  The data is stored in the column; block is bot.blockAt(position) read after that, with
  the data in block.entity and block.blockEntity. Not emitted when the column is not
  loaded. No 'blockUpdate' is emitted for it.

What writes blocks and emits 'blockUpdate' and 'blockUpdate:(x, y, z)'.
  - The server's block change message: one block.
  - The server's multi block change message: each block in it, one after the other.
  - The server's explosion message: each destroyed block is written as air (state 0).
    For these, the name of the per-position event is built from the explosion's centre
    plus the offset, without flooring: with a centre that has fractions the name has
    fractions, and listeners under the whole-number name are not called. 'blockUpdate'
    is emitted with floored positions.
  - bot.dig, when its time is over: air at the dug position.
  - Any bot.world.set... call (guide("world-object")).
  A write into a column that is not loaded does nothing and emits nothing.
  When the type of the block changes, a painting recorded at that position is forgotten.

What changes the copy without these events.
  - A chunk message: the whole column is loaded or replaced ('chunkColumnLoad',
    guide("chunk-events")).
  - Light messages.
  - Block entity data ('blockEntityData').

bot._updateBlockState(point, stateId)
  The write the messages above go through: bot.world.setBlockStateId(point, stateId),
  then the painting rule. It changes the bot's copy only; nothing is sent to the server.
