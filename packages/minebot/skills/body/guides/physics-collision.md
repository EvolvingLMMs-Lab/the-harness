guide("physics-collision"): how the simulated body collides with blocks: steps, edges with
sneak, bouncing, slowing blocks.

The body.
  A box 0.6 wide (bot.physics.playerHalfWidth 0.3 each way from bot.entity.position) and
  1.8 high (bot.physics.playerHeight), with bot.entity.position at the middle of its
  bottom. The simulation uses this box at all times, with sneak held too. It collides
  with the shapes of blocks (block.shapes) only.

One move.
  1. The move is the velocity of the tick. It is cut first in height, then along x, then
     along z, each to the distance at which the box meets a block shape.
  2. Step up: when the move was cut sideways, and the body is on the ground (or the
     same move was also cut downward), the move is tried again raised by up to 0.6
     (bot.physics.stepHeight). If that gets further sideways, the raised move is taken
     and the body is set down on what is under it. Blocks up to 0.6 high (slabs, stairs,
     a bed, snow layers) are climbed this way without a jump. A full block takes a jump.
     bot.physics.stepHeight = 0 turns stepping off.
  3. Flags on bot.entity:
       isCollidedHorizontally   the move was cut along x or z
       isCollidedVertically     the move was cut in height
       onGround                 the move was cut in height while going down
  4. Velocity: the x component becomes 0 when the move was cut along x, the z component
     when cut along z. When cut in height, velocity.y becomes 0; or, when the block 0.2
     under the feet is a slime block and sneak is not held, velocity.y changes sign (the
     body bounces).

sneak on the ground.
  With sneak held and bot.entity.onGround true, before the move: as long as the box
  moved sideways by the move would have no block shape under or around it (in the layer
  of blocks under the feet and up), the sideways move is shortened in steps of 0.05, down
  to 0. The body stops at the edge of the block it stands on.

Blocks that slow the body (after the move).
  The block tested is the one under the block the feet are in (position floored, then
  0.5 lower). Soul sand there: horizontal velocity times 0.4 (bot.physics.soulsandSpeed).
  Honey block there: times 0.4 (bot.physics.honeyblockSpeed), and a jump from it has 0.4
  of its height speed (bot.physics.honeyblockJumpSpeed).
  Cobweb and bubble column: guide("physics-liquid").

bot.physics.adjustPositionHeight(pos)
  pos: Vec3, changed in place. Lowers pos.y by up to 1 block, to the height where the body
  box at pos rests on the block shapes under it. With nothing within 1 block under it,
  pos.y becomes 1 lower. Returns undefined.

Blocks the simulation cannot see.
  A tick does nothing while the block at bot.entity.position is not loaded (bot.blockAt
  returns null): the body stays where it is, and no position is sent.
