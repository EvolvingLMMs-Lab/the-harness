guide("hand-use-item"): using the held item (bot.activateItem), filling a bucket
(bot.fillBucket) and pouring one (bot.pourBucket), and where a bucket puts and takes its
liquid.

bot.fillBucket(block) -> Promise of { item, from: [x, y, z] }
  Fills the empty bucket in the hand from the source of water or lava at block.position,
  when the source is in reach and in sight: some point of it is within 5 of the eyes, and
  it is in sight by the one test every act goes by (bot.inSight, as a block to dig is).
  It turns the head to it. Then
  the source is gone (air), and the hand holds the filled bucket; of more than one empty
  bucket in the hand, the hand keeps the others and the filled one goes into the
  inventory (to the ground at the feet when the inventory is full).
  item is 'water_bucket' or 'lava_bucket'.
  It goes by the server's command port, where the body was given one (the connection's
  rcon settings); without one it fails with "the server takes no commands here", and a
  bucket is used as any held item is (bot.activateItem below). So does bot.pourBucket.
  It fails, and nothing changed:
    the hand holds X, not an empty bucket
    (x, y, z) is ..., not a source of water or lava      (flowing liquid is not a source:
                                                          its block has a metadata above 0)
    the ... is N from the eyes; a bucket reaches 5
    not in sight: ... is behind a block                  (bot.inSight says no)
    the ... was no longer a source; nothing was taken    (it flowed away or was taken in the
                                                          moment between)
  It uses the channels use and look.
bot.pourBucket(at) -> Promise of { item, into: [x, y, z], liquid, evaporated? }
  Puts the liquid of the water or lava bucket in the hand into the cell at `at` (a Vec3
  or a block: the cell it is in), when the cell is in reach and in sight: some point of
  it is within 5 of the eyes, and it is in sight by bot.inSight.
  It turns the head to it. Then the cell holds a source of that liquid, and the
  hand holds an empty bucket.
  The cell takes the liquid when it is air, a liquid, or a block the body walks through:
  that block is broken first and drops what breaking it drops. Water in the Nether is
  gone at once (the dimension is too warm): nothing is put in the cell, evaporated is
  true, and the hand holds an empty bucket.
  item is 'bucket'; liquid is 'water' or 'lava'.
  It fails, and nothing changed:
    the hand holds X, not a water or lava bucket
    (x, y, z) is not loaded
    (x, y, z) is X: liquid goes into air, a liquid or a block the body walks through
    (x, y, z) is N from the eyes; a bucket reaches 5
    not in sight: ... is behind a block                  (bot.inSight says no)
    (x, y, z) changed in the moment between; nothing was poured
  It uses the channels use and look.

bot.activateItem(offHand = false)
  Synchronous; returns nothing. Sets bot.usingHeldItem to true and sends one use-item
  packet with hand 0 (main hand), or hand 1 (off hand) when offHand is true. This is the
  right mouse button pressed with no block targeted. It checks nothing (an empty hand
  also sends the packet) and waits for nothing.

A bucket in the hand (measured in this game version).
  bot.activateItem() names no block. The game decides the cell itself, from where the
  head faces at that moment: it draws a line from the eyes (1.62 above the feet) the way
  the head faces and takes the first block the line meets. Turn the head first
  (bot.lookAt(point, true)), then wait one tick (await bot.waitForTicks(1)): the packet
  carries no direction, and the head's turn goes to the game only with the next tick. A
  use sent right after the turn is judged by where the head faced before.
  water_bucket, lava_bucket
    The liquid goes into the cell on the outer side of the face the line meets: beside a
    side face, on top of a top face. Whatever block is nearer on the line is the one
    that is met: with a block right in front of the eyes, the liquid went into the cell
    of the body's own head. The line goes through water: lava aimed at a face with a
    water source in front of it went into that cell. bot.pourBucket(at) puts it into the
    cell it is given, where such a line to it shows.
  bucket (empty)
    The liquid is taken when the first thing the line meets is a source of water or
    lava. Flowing water is not taken, and the line goes through it. With a block
    between the eyes and the source nothing is taken: any block with an outline, also
    one the body walks through (grass, a flower, a cobweb, a torch, fire). bot.fillBucket(block)
    fills from the source it is given, where such a line to it shows.
  Reach: a face 4.5 from the eyes was met; a face 5.5 from them was not.
  The call reports nothing and waits for nothing: what happened is read afterwards, from
  the cell (bot.blockAt) and from the item in the hand (water_bucket or lava_bucket
  becomes bucket, and back).
  What a line from the eyes meets first can be read before the call: guide("raycast").

bot.deactivateItem()
  Synchronous; returns nothing. Sends one block-dig packet with status 5 (release the
  used item), position (0, 0, 0), face 0, and sets bot.usingHeldItem to false.

bot.usingHeldItem                    boolean, false at start
  true from bot.activateItem (and so from bot.consume). Set to false by:
  bot.deactivateItem; any entity-status packet, for any entity and any status; a
  set-cooldown packet when the hand is empty or its item id equals the held item's type;
  a 'heldItemChanged' event emitted while the hand holds an item.

bot.activateBlock(block, direction, cursorPos) -> Promise
  A right click on a block with the main hand: guide("block-activate").
bot.activateEntity(entity), bot.activateEntityAt(entity, position) -> Promise
  A right click on an entity with the main hand: guide("entity-use").
bot.consume() -> Promise
  Eating or drinking the held item, built on bot.activateItem: guide("consume").

Opening a window with a right click (bot.openBlock, bot.openEntity) is in
guide("window-open-close").
