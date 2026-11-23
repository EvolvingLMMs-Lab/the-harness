guide("block-action-events"): note blocks, pistons, lids, and the breaking of blocks seen.

All are events on bot. The first three come from the server's block action message. The
message is dropped when the block at its position is not loaded or when its block id is
not in the registry. block is bot.blockAt(position) at that moment.

'noteHeard' (block, instrument, pitch)
  The message names a note_block. instrument and pitch are read from the state of the
  block in the bot's copy, not from the message:
  instrument: { id, name }, name one of harp, basedrum, snare, hat, bass, flute, bell,
  guitar, chime, xylophone, iron_xylophone, cow_bell, didgeridoo, bit, banjo, pling
  (ids 0 to 15 in this order). pitch: a number from 0 to 24.

'pistonMove' (block, byte1, byte2)
  The message names a piston or a sticky_piston. byte1 and byte2 are the two numbers of
  the message, passed on as they are.

'chestLidMove' (block, count, block2)
  The message names any other block (chest, trapped_chest, ender_chest, shulker boxes,
  barrel, bell ...). count is the second number of the message: for containers the
  number of players that have it open, 0 when closed.
  It is emitted only when count differs from the last count kept for that position (the
  count is kept while it is above 0).
  For chest and trapped_chest, the half is read from the block's state:
  - state type 'single': block2 is null.
  - state type 'left': block2 is the neighbouring block, taken from the facing: facing
    north: the block to the east; south: west; west: north; east: south.
  - state type 'right': nothing is emitted, so a double chest gives one event.
  For every other block block2 is null.

'blockBreakProgressObserved' (block, destroyStage, entity)
  The server's block break animation message with a stage from 0 to 9. block is
  bot.blockAt(position) (null when not loaded), entity is bot.entities[id] of the
  breaker (undefined when unknown).

'blockBreakProgressEnd' (block, entity)
  The same message with a stage below 0 or above 9: the animation is removed. It says
  nothing about whether the block was broken.
