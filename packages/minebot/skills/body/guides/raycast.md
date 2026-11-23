guide("raycast"): rays through the loaded world: what a ray meets, what the head points at.

bot.world.raycast(from, direction, range, matcher = null) -> Block | null
  from: Vec3, the start. direction: Vec3 of length 1 (range is counted in multiples of
  its length). range: number.
  It walks the block positions the ray crosses, in order, starting with the position that
  holds from. It ends when the next position is entered at more than range from the
  start, and returns null. Positions in columns that are not loaded are passed over.
  Without matcher: it returns the first block whose shapes (block.shapes, the collision
  boxes) the ray crosses. The crossing is tested on the whole line, not cut at range, so
  the hit point can be a little farther than range; a start inside a block's box
  returns that block, with a hit point behind the start. Blocks with no shapes (air, water,
  lava, plants, torches, signs) are passed through. The returned Block has
    block.face        the face the ray entered by: 0 bottom (-y), 1 top (+y),
                      2 north (-z), 3 south (+z), 4 west (-x), 5 east (+x)
    block.intersect   Vec3, the point where the ray meets the box
  With matcher: matcher(block, iterator) is called for every loaded position on the
  ray, air included, and the first block for which it returns truthy is returned as it
  is. Shapes are not tested, and face and intersect are not set. iterator.intersect(
  block.shapes, block.position) gives { pos, face } or null for that block
  (guide("world-iterators")).

bot.blockAtCursor(maxDistance = 256, matcher = null) -> Block | null
  bot.blockAtEntityCursor(bot.entity, maxDistance, matcher).

bot.blockAtEntityCursor(entity = bot.entity, maxDistance = 256, matcher = null)
    -> Block | null
  The block the entity's head points at: bot.world.raycast from
  entity.position.offset(0, entity.height, 0) along the direction of its yaw and pitch,
  (-sin(yaw) * cos(pitch), sin(pitch), -cos(yaw) * cos(pitch)), with range maxDistance.
  The start is the full height of the entity (1.8 for the bot standing, 1.5 sneaking),
  not its eye height (1.62, 1.27).
  Returns null without casting when entity.position, entity.height, entity.pitch or
  entity.yaw is missing or 0: a pitch of exactly 0 (level) or a yaw of exactly 0 gives
  null.

What the eyes see: bot.inSight, bot.blockInSight, bot.entityInSight.
  The body's own test of sight, the one its acts use (bot.dig, activateBlock, openBlock,
  sleep, craft at a table, attack, activateEntity, activateEntityAt, openEntity fail with
  'not in sight: ...' when it is false; bot.placeBlock tests the cell the block goes to,
  bot.blockInSight(bot.blockAt(dest))). It uses no channel and is not gated.
  bot.inSight(target, from, through) -> boolean
    target: a Block or an Entity. from: a Vec3 to look from instead of the eyes
    (bot.entity.position + 1.62 up). through: a Vec3 of a block to count as gone.
    true when target is missing or has no position, when it is the body's own entity
    (without from), or when the eye point is inside the target's box.
    Otherwise each side of the target's box that faces the eye point is tested at a 5 by
    5 grid of points (at 0.02, 0.26, 0.5, 0.74 and 0.98 across the side). A Block's box
    spans its shapes (a block with no shapes: the whole cell); an Entity's box is its
    width (0.6 when unknown) by its height (1.8 when unknown) around its position.
    A point shows when bot.world.raycast from the eye point to it, for a block with
    shapes: meets that block first; for anything else: meets nothing nearer than the
    point (within 0.02). With through, a ray stopped by the block at `through` counts
    when a ray back from the point meets nothing or that block. Blocks with no shapes
    (air, water, plants) hide nothing.
    true at the first point that shows; false when none does.
  bot.blockInSight(block) -> boolean     bot.inSight(block)
  bot.entityInSight(entity) -> boolean   bot.inSight(entity)
  bot.blockInSight takes the place of Mineflayer's own bot.blockInSight(maxSteps,
  vectorLength) (the block the head points at); that one is bot.blockAtCursor here.

bot.canSeeBlock(block)         the same as bot.blockInSight(block)
bot.entityAtCursor(maxDistance = 3.5)       the entity the head points at; it first calls
                               bot.blockAtCursor(maxDistance) and does not look past
                               that block
