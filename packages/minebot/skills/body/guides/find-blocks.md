guide("find-blocks"): bot.findBlocks and bot.findBlock: searching the loaded world.

bot.findBlocks(options) -> [Vec3]
  Returns positions (not blocks), sorted by distance to the start point, smallest first,
  at most count of them; [] when nothing matches. It reads the bot's copy of the world and
  returns in the same call.

  options.matching      a block id, an array of block ids, or a function (block) -> truthy.
                        Ids are compared with block.type.
  options.point         Vec3, default bot.entity.position. It is floored.
  options.maxDistance   number, default 16 (0 also gives 16).
  options.count         number, default 1 (0 also gives 1).
  options.useExtraInfo  false (default), true, or a function (block) -> truthy.

How it searches.
  The world is cut into sections of 16 x 16 x 16 blocks. The search starts in the section
  of the start point and goes outwards in layers: layer n is every section whose section
  coordinates differ from the start section by |dx| + |dy| + |dz| = n. The last layer is
  n = ceil((maxDistance + 8) / 16): 2 for maxDistance 16, 3 for 32, 5 for 64. A section
  outside these layers is not searched, whatever the distance of its blocks: with
  maxDistance 16, the section one step away on all three axes (sum 3) is not searched.
  Sections of columns that are not loaded, and sections below y 0 or above y 255, are
  skipped.
  Before reading a section it tests the section's list of block states (its palette):
  matching is called once for each state in the list with a Block that has
  position null, light 0 and no block entity. When no state passes, the section is
  skipped. A matching function that reads block.position throws on these calls.
  With useExtraInfo true this test is not done and every section is read.
  In a section that passed, each of the 4096 positions is tested:
    useExtraInfo false:      matching(bot.blockAt(pos, false))
    useExtraInfo true:       matching(bot.blockAt(pos, true))
    useExtraInfo a function: matching(block) && useExtraInfo(block), with
                             block = bot.blockAt(pos, true)
  Here the block has its position. A position is kept when the test passes and its
  distance to the start point is at most maxDistance. The distance is measured between
  the whole-number position of the block and the floored start point.
  The search stops when it has count positions, checked when a layer is complete (the
  first section of the following layer is read before the check). The start section alone
  ends the search when it already holds count positions. A nearer block in a section of
  a later layer is then not in the result.
  Then the positions are sorted by distance and cut to count.

bot.findBlock(options) -> Block | null
  Same options. Returns bot.blockAt(first position of bot.findBlocks(options)), or null
  when the list is empty.

Going to what was found.
  The list is ordered by straight-line distance from the start point, through walls,
  water and rock. A position in it can be under water, or far above or below the body.
  Nothing moves the body to a position found: code moves it with the keys and the head
  (guide("control-keys"), guide("look")). What lies between the body and the position is
  read with bot.blockAt (guide("block-at")) and rays (guide("raycast")).
