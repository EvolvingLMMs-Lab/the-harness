guide("place-block-options"): bot._placeBlockWithOptions and bot._genericPlace.

bot._placeBlockWithOptions(referenceBlock, faceVector, options) -> Promise<void>
  bot.placeBlock with options chosen by the caller. options is an object ({} is
  accepted; undefined throws a TypeError). It reads the old block at
  referenceBlock.position.plus(faceVector), calls bot._genericPlace with the same three
  arguments, then waits for the block update and settles as guide("place-block") says in
  steps 5 and 6.

bot._genericPlace(referenceBlock, faceVector, options) -> Promise<Vec3>
  Sends one click on a face of referenceBlock and resolves with referenceBlock.position
  as soon as the click is sent. It waits for no answer of the server.

  options.offhand     false (default): the right hand; with bot.heldItem empty it rejects
                      'must be holding an item to place'.
                      true: the off hand; with inventory slot 45 empty it rejects
                      'must be holding an item in the off-hand to place'.
  options.half        'top' or 'bottom'. Read only when faceVector.y is 0 (a side face):
                      the click's height on the face is 0.75 for 'top', 0.25 for
                      'bottom', 0.5 without it.
  options.delta       a Vec3, each part from 0 to 1: the point of the click measured from
                      referenceBlock's corner. It replaces the point computed from
                      faceVector and half. Without it the point is
                      0.5 + faceVector * 0.5 on each axis.
  options.forceLook   passed to bot.lookAt(referenceBlock.position + point, forceLook).
                      undefined or false (default): waits until the turned yaw has been
                      sent to the server. true: the head is set at once, no wait.
                      'ignore': the head does not turn.
  options.swingArm    'right' or 'left': swings that arm before the click is sent.
                      undefined (default): no swing. bot.placeBlock passes 'right'.
  options.showHand    passed to bot.swingArm(arm, showHand). Default true: the swing
                      names the hand. false: the swing is sent without a hand.

  Order: the hand check, the look, the swing, the click. The click carries
  referenceBlock.position, the face number of faceVector (y < 0: 0, y > 0: 1, z < 0: 2,
  z > 0: 3, x < 0: 4, x > 0: 5; all zero throws 'invalid direction vector (0, 0, 0)'),
  the hand (0 right, 1 off hand), the point, and 'inside block' false.
