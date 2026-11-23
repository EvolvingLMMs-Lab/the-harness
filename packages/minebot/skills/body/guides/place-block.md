guide("place-block"): bot.placeBlock: what it sends, what it waits for, its errors.

bot.placeBlock(referenceBlock, faceVector) -> Promise<{placed, at, seconds}>
  referenceBlock: a Block that is there (its position is read).
  faceVector: a Vec3 naming one face of it: (0, 1, 0) top, (0, -1, 0) bottom,
  (0, 0, -1) north, (0, 0, 1) south, (-1, 0, 0) west, (1, 0, 0) east.
  The new block is expected at dest = referenceBlock.position.plus(faceVector).
  It places the item in the right hand (bot.heldItem). It is
  bot._placeBlockWithOptions(referenceBlock, faceVector, { swingArm: 'right' });
  the options: guide("place-block-options").
  It does not check the distance, what the held item is, or what is at dest.
  It uses the channels use and look (guide("run-channels")): code that did not say it
  uses both gets the channel error and nothing is sent. The place the block goes
  to (referenceBlock.position + faceVector) must be one the eyes could see from where
  the body stands, turning the head as they like: some point of that cell with no block
  between it and the eyes. The head need not be turned there and the face the block is
  put against need not show; a place behind a block (through a wall, past the edge of
  the floor the body stands on) rejects with 'not in sight: the place at (x, y, z) is
  behind a block; ...', and nothing is sent. The test is bot.blockInSight(bot.blockAt(dest))
  (guide("raycast")): code can ask it of a cell before it places there.

  What it resolves with. The body runs the steps below, then reads the block at dest
  from the bot's copy of the world:
    placed   the name of the block at dest when its bounding box is 'block' (a full
             block's shape); null otherwise, also when nothing was placed
    at       {x, y, z} of dest
    seconds  from the call to the end of the steps, 2 decimals
  When the steps below reject, the call rejects with that error only when `placed` would
  be null; when a block with a full shape is at dest, it resolves with the object above
  instead. When the steps resolve, it resolves, also with placed null (a block without
  a full shape, such as a torch, is placed with placed null).

  Steps, in order.
  1. It reads the block at dest (the old block).
  2. Empty hand: rejects 'must be holding an item to place'.
  3. It looks at the middle of the face (referenceBlock.position + 0.5 + faceVector * 0.5)
     and waits until the turned yaw has been sent to the server.
  4. It holds sneak down for the click (released after step 5, unless it was down
     before), as a player places: a block put against a furnace, a chest, a crafting
     table or a door is placed, and the furnace is not opened nor the door turned.
     It swings the right arm and sends the click to the server: the position of
     referenceBlock, the face number (y < 0: 0, y > 0: 1, z < 0: 2, z > 0: 3, x < 0: 4,
     x > 0: 5, read in this order), the right hand, and the point of the click on the
     block (0.5 + faceVector * 0.5 on each axis). A faceVector of (0, 0, 0) throws
     'invalid direction vector (0, 0, 0)'.
  5. It waits up to 5000 ms for a block update at dest. An update for referenceBlock's
     position that arrives after the click is taken as the server's answer to the click.
     The wait ends at the first update for dest that
       - changes the type of the block there, or
       - comes after the answer, while no other placeBlock call is waiting on the same
         dest, or
       - is the (null, null) sent when the world is unloaded.
  6. Result of the steps.
       The update came with null blocks: resolves, no event.
       The new block has the type of the old block read in step 1: rejects
         'Server refused to place <held item name, or block> at <dest>: the block is
          still <name>'.
       Otherwise: emits 'blockPlaced' (oldBlock, newBlock) and resolves.
       5000 ms pass with no such update:
         no answer was seen: rejects 'Server did not answer the placement at <dest>:
           Event blockUpdate:<dest> did not fire within timeout of 5000ms'
         an answer was seen (another call was waiting on the same dest): rejects
           'Event blockUpdate:<dest> did not fire within timeout of 5000ms'.
     <dest> is written as '(x, y, z)'.
  With the column of dest not loaded in step 1, a later update for dest ends in a
  TypeError.

Event on bot.
  'blockPlaced' (oldBlock, newBlock)   a placeBlock call saw the type at dest change.
                                       oldBlock is the block read in step 1
