guide("bed"): bot.sleep, bot.wake, bot.isABed, bot.isSleeping, every check and error, the
'sleep', 'wake' and 'spawnReset' events.

bot.sleep(bedBlock) -> Promise
  bedBlock: a Block (either half of a bed). Checks in this order; rejects at the first
  that fails, before anything is sent:
  1. "it's not night and it's not a thunderstorm": bot.time.timeOfDay is outside 12541 to
     23458, and not (bot.isRaining true and bot.thunderState above 0).
  2. 'already sleeping': bot.isSleeping is true.
  3. 'wrong block : not a bed block': bot.isABed(bedBlock) is false.
  4. 'the bed is occupied': the block's state says occupied.
  5. "there's only half bed": bedBlock is a foot half, the block one step toward its
     head is not a bed, and the block one step the other way is not a bed either.
     (Foot half with a bed block toward the head: that block is the head. Foot half with
     a bed block only on the other side: that other block is clicked, and the given
     block counts as the head.)
  6. 'cant click the bed': bot.canDigBlock(bedBlock) is false.
  7. 'the bed is too far': with d = the body's block position (bot.entity.position
     floored) minus the head block's position, d.x is outside -3 to 2, or d.y outside -2
     to 2, or d.z outside -3 to 2. On the side where the foot lies the limit is one more:
     head north of the foot: d.z up to 3; head south: d.z down to -4; head west: d.x up
     to 3; head east: d.x down to -4.
  8. 'there are monsters nearby': an entity in bot.entities with kind 'Hostile mobs'
     whose floored position minus the head block's position has x in -8 to 7, y in -6 to
     4 and z in -8 to 7. Tested in every game mode.
  Then it calls bot.activateBlock(bedBlock) (a right click on the bed) and waits for the
  'sleep' event.
  Resolves with undefined at 'sleep'.
  Rejects with 'bot is not sleeping' when no 'sleep' event comes within 3000 ms of the
  click. The reason the server refused is not known to the call.

bot.wake() -> Promise
  Rejects with 'already awake' when bot.isSleeping is false. Else sends the 'stop
  sleeping' entity_action packet and resolves with undefined at once; it does not wait
  for the 'wake' event.

bot.isABed(block) -> boolean
  true when block.name is one of: white_bed, orange_bed, magenta_bed, light_blue_bed,
  yellow_bed, lime_bed, pink_bed, gray_bed, light_gray_bed, cyan_bed, purple_bed,
  blue_bed, brown_bed, green_bed, red_bed, black_bed, bed.

bot.parseBedMetadata(bedBlock) -> object
  Reads the block state. Returns { part, occupied, facing, headOffset }:
  part: true for the head half, false for the foot half. occupied: boolean.
  facing: 0 south, 1 west, 2 north, 3 east: the direction from foot to head.
  headOffset: Vec3, one step in that direction ((0, 0, 1) for south).

bot.isSleeping                       boolean, false at creation
  true from the 'sleep' event, false from the 'wake' event.

Events.
  'sleep' ()        the server shows the body's own entity lying in a bed ('entitySleep'
                    for bot.entity). bot.isSleeping is already true.
  'wake' ()         the server sends the leave-bed animation for the body's own entity
                    ('entityWake' for bot.entity). bot.isSleeping is already false.
  'spawnReset' ()   the server reports that no respawn block is available: the spawn
                    point set at a bed is gone
