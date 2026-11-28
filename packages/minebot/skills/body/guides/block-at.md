guide("block-at"): reading the block at a position from the bot's copy of the world.

The bot keeps its own copy of the world, built from what the server sends. It holds the
columns (16 x 16 blocks, y 0 to 255) the server has sent and not unloaded. Every read below
reads this copy.

bot.blockAt(point, extraInfos = true) -> Block | null
  point: a Vec3; fractions are floored.
  Returns null when the column holding the point is not loaded.
  Otherwise returns a new Block object made at the moment of the call, with
  block.position set to the floored point. Two calls give two objects. The object keeps
  the values it was made with; a later change of the world does not change it.
  In a loaded column, a y below 0 or above 255 gives a block named 'air'.
  A column that was created by a light packet before its blocks arrived gives 'air'
  everywhere (see guide("chunk-events")).
  extraInfos true: block.painting is set to the painting recorded at that position
  ({ id, position, name, direction }), or undefined when there is none.
  extraInfos false: block.painting is not set.
  The fields of the result: guide("block-object"). Its methods: guide("block-methods").

bot.canSeeBlock(block) -> boolean
  The same as bot.blockInSight(block): the body's own test of sight, the one its acts use
  (guide("raycast")). It takes the place of Mineflayer's own bot.canSeeBlock (one ray to
  the block's centre).

bot._getBlockAtEyeLevel() -> Block | null
  bot.blockAt(bot.entity.position.offset(0, bot.entity.eyeHeight, 0)).

Related calls.
  bot.findBlocks, bot.findBlock        guide("find-blocks")
  bot.blockAtCursor, bot.world.raycast guide("raycast")
  bot.world.getBlock and the others    guide("world-object")
