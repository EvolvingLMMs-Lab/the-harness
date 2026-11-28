guide("place-entity"): bot.placeEntity: boats, end crystals, armor stands, spawn eggs.

bot.placeEntity(referenceBlock, faceVector) -> Promise<Entity>
  referenceBlock is the Block that is clicked. faceVector is a Vec3 with one axis at 1 or
  -1 naming the clicked face, for example new Vec3(0, 1, 0) for the top.
  Steps, in order:
  1. bot.heldItem is null: rejects with 'must be holding an item to place an entity'.
  2. The name of the item in the main hand is checked. Accepted: 'end_crystal',
     'armor_stand', every name ending in '_boat', every name ending in '_spawn_egg'.
     Any other item: rejects with an AssertionError whose message is 'Unimplemented'.
  3. Awaits bot.lookAt at the centre of the clicked face: referenceBlock.position plus
     (0.5 + 0.5 * faceVector.x, 0.5 + 0.5 * faceVector.y, 0.5 + 0.5 * faceVector.z).
  4. Sends an arm swing for the main hand (bot.swingArm('right'); for a spawn egg with
     showHand false).
  5. Sends one block placement packet: the position of referenceBlock, the face, the
     main hand, the same point on the face as the cursor, insideBlock false.
     A faceVector of (0, 0, 0) fails here with an AssertionError 'invalid direction
     vector (0, 0, 0)'.
  6. For a boat only: also sends one use-item packet for the main hand.
  7. Waits for the entity. The expected entity.name is 'boat' for every boat,
     'end_crystal', 'armor_stand', and for an egg the item name without '_spawn_egg'
     ('zombie_spawn_egg' -> 'zombie'). The target point is referenceBlock.position plus
     faceVector (whole-number coordinates). Only the next 'entitySpawn' event after
     step 6 is looked at, whatever entity it is about:
       its entity.name equals the expected name and its position is less than 2 blocks
       from the target point (3 for a boat, 4 for a bat): the wait ends with that entity;
       otherwise nothing more is looked at and the wait runs into the time limit.
     Time limit: 5000 ms from the start of step 7, then it rejects with
     'Failed to place entity'. The same rejection comes when no entity appears at all.
  8. Emits 'entityPlaced' (entity) on bot and resolves with the Entity.
  It checks no distance to the block and does not check that the face is free. Nothing
  is retried.

'entityPlaced' (entity)
  Emitted on bot by step 8, just before the promise resolves.

bot._placeEntityWithOptions(referenceBlock, faceVector, options) -> Promise<Entity>
  The same steps with settings. bot.placeEntity calls it with {}.
  options.forceLook   passed as the second argument of bot.lookAt in step 3; the value
                      'ignore' skips step 3
  options.offhand     true: steps 4 to 6 use the off hand (swing 'left'), and an empty
                      off-hand slot (inventory slot 45) rejects with 'must be holding an
                      item in the off-hand to place'. Steps 1, 2 and 7 still read the
                      item in the main hand.
  options.swingArm    'right' or 'left'; default 'left' with offhand, else 'right'
  options.showHand    passed to bot.swingArm; forced to false for a spawn egg
  options.delta       Vec3; replaces the point on the face (as offsets 0 to 1 inside the
                      block) used in steps 3 and 5
  options.half        'top' or 'bottom': on a side face moves that point 0.25 up or down
