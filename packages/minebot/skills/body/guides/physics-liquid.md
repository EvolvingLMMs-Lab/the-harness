guide("physics-liquid"): what the simulation does in water and lava, in a bubble column and
in a cobweb, with the speeds.

When the body counts as in water or lava (tested at the start of each tick).
  bot.entity.isInWater: a water block lies in the part of the body from 0.401 to 1.399
    above the feet (0.598 wide). Water blocks are: water, seagrass, tall seagrass, kelp,
    kelp plant, bubble column, and every waterlogged block.
  bot.entity.isInLava: a lava block lies in the part of the body from 0.4 to 1.4 above the
    feet (0.4 wide).
  The test goes by whole blocks: every block that the range reaches is looked at, and
  one water (or lava) block among them is enough. A liquid block that only the lowest
  0.4 of the body reaches does not count: the body moves as on land.

The current.
  Each water block the body is in pushes along its flow. The pushes are added, and the
  sum, scaled to length 0.014, is added to the velocity each tick.

One tick in water or lava (in place of steps 4 to 9 of guide("physics-keys")).
  1. jump held: velocity.y plus 0.04 (before anything else). bot.jumpTicks is not used.
  2. The direction keys give an acceleration of 0.02 (bot.physics.liquidAcceleration),
     with the same input rules as on land. sneak: input times 0.3. sprint: no effect.
  3. The body moves by its velocity and collides.
  4. velocity.y times 0.8 in water, times 0.5 in lava; then minus 0.005 in water, minus
     0.02 in lava (an eighth of that with Slow Falling while velocity.y is 0 or less).
  5. Horizontal velocity times 0.8 in water, times 0.5 in lava.
  6. Leaving the liquid: when the move was blocked sideways and the body, moved on by its
     velocity and raised by 0.6, would touch no block and no water, velocity.y is set to
     0.3 (bot.physics.outOfLiquidImpulse).

In water only.
  Depth Strider on the boots (level up to 3; counted half while not on the ground):
    horizontal factor of step 5 = 0.8 + (0.546 - 0.8) * level / 3; acceleration =
    0.02 + (0.7 - 0.02) * level / 3.
  Dolphin's Grace: the horizontal factor of step 5 is 0.96.

Speeds that follow, in water, no enchantment.
  No key held: the body sinks 0.025 blocks a tick, 2 seconds a block.
  jump held: it rises 0.175 blocks a tick (3.5 blocks a second).
  A direction key held: 1.96 blocks a second.
  sneak does not move the body down.
In lava: no key held it sinks 0.04 blocks a tick; jump held it rises 0.04 a tick.

Bubble column (the body touches a bubble column block; after the move).
  A column that pulls down (block metadata 0): velocity.y = max(-0.3, velocity.y - 0.03);
  with air above the column block: max(-0.9, velocity.y - 0.03).
  A column that pushes up: velocity.y = min(0.7, velocity.y + 0.06); with air above:
  min(1.8, velocity.y + 0.1).

Cobweb.
  bot.entity.isInWeb becomes true when the body touches a cobweb block after a move. The
  next move is cut to a quarter sideways and a twentieth in height, the velocity is set
  to 0, and isInWeb is tested again.

Measured in the game.
  With no key held the body sinks in water, 2 seconds a block; jump swims up.
