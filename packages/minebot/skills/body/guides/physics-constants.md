guide("physics-constants"): every field of bot.physics, the numbers the simulation runs on.

bot.physics
  One object, made when the bot is created. The simulation reads each field at each use:
  writing a number to a field changes the simulation from the next tick. Units are blocks
  and ticks (a tick is 0.05 s) unless said.

  gravity               0.08      taken from velocity.y each tick out of liquid
  airdrag               0.98      velocity.y is multiplied by it each tick out of liquid
  yawSpeed              3.0       radians a second: how fast the sent yaw follows
  pitchSpeed            3.0       radians a second: how fast the sent pitch follows
  playerSpeed           0.1       the speed attribute when the server has sent none
  sprintSpeed           0.3       sprint multiplies the speed attribute by 1 + this
  sneakSpeed            0.3       sneak multiplies the key input by this
  stepHeight            0.6       the height climbed without a jump; 0: no stepping
  negligeableVelocity   0.003     a smaller velocity component becomes 0 (spelled so)
  soulsandSpeed         0.4       horizontal velocity factor over soul sand
  honeyblockSpeed       0.4       horizontal velocity factor over a honey block
  honeyblockJumpSpeed   0.4       factor on the jump speed 0.42 over a honey block
  ladderMaxSpeed        0.15      limit of horizontal speed and of the fall on a ladder
  ladderClimbSpeed      0.2       velocity.y when climbing a ladder
  playerHalfWidth       0.3       half the width of the body box
  playerHeight          1.8       height of the body box
  waterInertia          0.8       velocity factor each tick in water
  lavaInertia           0.5       velocity factor each tick in lava
  liquidAcceleration    0.02      acceleration from the direction keys in water and lava
  airborneInertia       0.91      horizontal velocity factor each tick in the air
  airborneAcceleration  0.02      acceleration from the direction keys in the air
  defaultSlipperiness   0.6       slipperiness of every block without its own value
  outOfLiquidImpulse    0.3       velocity.y when leaving a liquid against a block
  autojumpCooldown      10        ticks bot.jumpTicks is set to at a jump
  bubbleColumnSurfaceDrag   { down: 0.03, maxDown: -0.9, up: 0.1, maxUp: 1.8 }
  bubbleColumnDrag          { down: 0.03, maxDown: -0.3, up: 0.06, maxUp: 0.7 }
  slowFalling           0.125     factor on gravity with Slow Falling while not rising
  waterGravity          0.005     taken from velocity.y each tick in water
  lavaGravity           0.02      taken from velocity.y each tick in lava
  movementSpeedAttribute    'generic.movement_speed'   the key read in bot.entity.attributes
  sprintingUUID         '662a6b8d-da3e-4c1c-8813-96ea6097278d'   uuid of the sprint modifier

  waterGravity and lavaGravity are computed once at creation as gravity / 16 and
  gravity / 4. Writing gravity later does not change them.

Numbers in the simulation that are not fields (fixed in the code).
  jump speed 0.42; 0.1 more for each Jump Boost level; 0.2 forward at a sprint jump
  jump in water or lava: 0.04 a tick
  key input factor 0.98
  sprint in the air: 0.3 * airborneAcceleration more
  slipperiness: slime block 0.8; ice, packed ice, frosted ice 0.98; blue ice 0.989
  ground acceleration: speed attribute * 0.1627714 / (slipperiness * 0.91)^3
  water current 0.014 a tick; cobweb 0.25 sideways and 0.05 in height
  Depth Strider targets: horizontal factor 0.546, acceleration 0.7; Dolphin's Grace 0.96
  Levitation: velocity.y moves 0.2 of the way to 0.05 * level each tick
  elytra and firework numbers: guide("elytra")

bot.physics.simulatePlayer(state, world) -> state
  Runs one tick on a player state object and returns the same object, changed. The bot
  calls it once a tick with a state built from bot.entity, the keys, bot.jumpTicks,
  bot.jumpQueued, bot.fireworkRocketDuration, the effects and the boots, and copies the
  result back: guide("physics-state").

bot.physics.adjustPositionHeight(pos)      guide("physics-collision")
