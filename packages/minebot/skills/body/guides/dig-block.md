guide("dig-block"): bot.dig: what it sends, what it waits for, how it ends.

bot.dig(block, forceLook, digFace) -> Promise<{dug, at, tool, seconds, gone}>
  block: a Block (its position, name and shapes are read).
  forceLook and digFace: where the head turns and which face is sent,
  guide("dig-face"). Both are optional.
  It digs with the item in the hand. It does not choose or equip a tool: code equips the
  tool first (guide("equip")). It does not check the distance, block.diggable, the tool,
  or that the block is still there. Nor what is around the block: a block with lava
  above it or beside it (a source or a flow) lets the lava flow into its cell once dug.
  It uses the channels use and look (guide("run-channels")): code that did not say it
  uses both gets the channel error and nothing is dug.
  The block must be in sight: when no line from the eyes reaches it without another
  block in between, it rejects with 'not in sight: <name> at (x, y, z) is behind a block;
  dig only what the body can see' and notes the event not_in_sight.

  What it resolves with.
    dug      the block's name, read before the dig
    at       {x, y, z} of the block's position
    tool     the name of the item in the hand when the call began; null: the bare hand
    seconds  from the call to the end of the dig, 2 decimals (the turn of the head
             included)
    gone     true when the block at that position, as the bot's copy of the world has it
             at the end, is missing or has another name than `dug`
  A dig that resolves is counted in `did.dug` of the running job on use
  (guide("run-report")).

  Steps, in order.
  1. block null or undefined: rejects 'dig was called with an undefined or null block'.
  2. It computes the time with bot.digTime(block) (guide("dig-time")), from the state at
     this moment. Infinity: rejects 'dig time for <block.name> is Infinity'.
  3. It turns the head (unless forceLook is 'ignore') and, without forceLook, waits for
     the turn.
  4. If another dig is running (bot.targetDigBlock is set) it calls bot.stopDigging():
     that dig rejects with 'Digging aborted'.
  5. It sends the start of the dig (position and face) to the server, sets
     bot.targetDigBlock = block, swings the arm, and swings it again every 350 ms.
  6. After the computed time it sends the end of the dig, sets bot.targetDigBlock and
     bot.targetDigFace to null, sets bot.lastDigTime, and writes air (state 0) at the
     position into the bot's copy of the world.
  7. That write emits the block update for the position with an air block; the dig then
     emits 'diggingCompleted' and resolves with the object above.

  Other ways it ends.
  - The server reports air at the position before the time is over: the timers are
    cleared, 'diggingCompleted' is emitted and it resolves; the end of the dig is not
    sent.
  - A block update for the position that is not air (type 0) is ignored.
  - bot.stopDigging(), a second bot.dig, or the bot's death: rejects 'Digging aborted'.
  - The column of the block is not loaded when the time is over: nothing is written, no
    update is emitted, and the promise stays pending.
  - The dimension changes during the dig: every column is unloaded, the dig's listener is
    removed (when it is the only listener on bot for that position) and the promise stays
    pending.
  It resolves on its own clock. The bot's copy says air from that moment. A block the game
  did not let it dig is put back afterwards, when the game's answer to the dig arrives
  (the event dig_refused {at, block} is noted then); `gone` is read at the end of the
  dig, before that answer.

bot.stopDigging()
  No dig running (bot.targetDigBlock null): does nothing. While bot.dig is still turning
  the head, no dig is running yet.
  Otherwise: clears the timers, sends the cancel of the dig to the server, sets
  bot.targetDigBlock and bot.targetDigFace to null, sets bot.lastDigTime, emits
  'diggingAborted' (block), and the dig's promise rejects with 'Digging aborted'.

bot.canDigBlock(block) -> truthy | falsy
  block && block.diggable && the centre of the block (position + 0.5 on each axis) is at
  most 5.1 from bot.entity.position.offset(0, 1.65, 0). bot.dig does not call it.

bot.targetDigBlock      the Block being dug, or null. Set at step 5, null at the end
bot.targetDigFace       the face number sent, or null. Set at the start of bot.dig (before
                        the head turns), null at the end
bot.lastDigTime         performance.now() at the last end, completion or abort; null
                        before the first

Events on bot.
  'diggingCompleted' (block)   the dig ended with air there; block is the new air block
  'diggingAborted' (block)     a dig was stopped; block is the block that was being dug
  When the bot dies, all listeners of these two events are removed, then the dig stops.
