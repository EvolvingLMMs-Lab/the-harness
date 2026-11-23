guide("block-activate"): bot.activateBlock: clicking a block.

bot.activateBlock(block, direction, cursorPos) -> Promise<void>
  Clicks the block with the right hand (a door, a lever, a button, a bed, a chest).
  block: a Block (its position is read).
  direction: a Vec3 naming the face clicked; null or undefined gives (0, 1, 0), the top.
  It is turned into a face number, tested in this order: y < 0: 0 (bottom), y > 0: 1
  (top), z < 0: 2, z > 0: 3, x < 0: 4, x > 0: 5. All zero: it rejects with an
  AssertionError 'invalid direction vector (0, 0, 0)'; the head does not turn and nothing
  is sent.
  cursorPos: a Vec3, each part from 0 to 1: the point of the click measured from the
  block's corner; null or undefined gives (0.5, 0.5, 0.5).

  Steps, in order.
  1. await bot.lookAt(the centre of the block, false): it looks at position + 0.5 on each
     axis, whatever the direction, and waits until the turned yaw has been sent to the
     server.
  2. It sends one block-place packet: the block's position, the face number, hand 0 (the
     right hand), the point cursorPos, 'inside block' false.
  3. bot.swingArm(): it swings the right arm. Then it resolves with nothing.
  It resolves when the click is sent. It waits for no answer and does not check the
  distance or what the block is. It does not require an item in the hand. It does not
  change the sneaking state.
  With a block in the hand the click may place it.

The click is the same message bot.placeBlock sends (guide("place-block")); bot.placeBlock
also waits for the block update and requires an item in the hand.
