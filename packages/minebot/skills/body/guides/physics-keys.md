guide("physics-keys"): what each movement key does in the simulation, on the ground, in
the air and on a ladder, with the speeds.

One tick, in this order (20 ticks a second). Water and lava: guide("physics-liquid").
  1. Each velocity component smaller than 0.003 becomes 0.
  2. jump held (or bot.jumpQueued): on the ground with bot.jumpTicks 0, velocity.y is set
     to 0.42 (times 0.4 when the block under the feet's block is a honey block), plus 0.1
     for each level of Jump Boost. With sprint also held, 0.2 is added to the horizontal
     velocity along the facing direction. bot.jumpTicks becomes 10. A jump at 0.42 rises
     1.25 blocks. With jump held all the time the body jumps again at landing, at the
     earliest 10 ticks after the last jump.
  3. Input: forward minus back, and right minus left, each times 0.98. Two opposite keys
     cancel. sneak held: both times 0.3 (bot.physics.sneakSpeed). An input vector longer
     than 1 (two keys at a right angle, no sneak) is scaled to length 1: a diagonal is
     1 / 0.98 as fast as a straight line (4.41 against 4.32 blocks a second).
  4. Acceleration, added to the velocity along the input, turned by bot.entity.yaw
     (forward is the facing direction, right is 90 degrees clockwise from it seen from
     above):
     on the ground (bot.entity.onGround): speed attribute * 0.1627714 / f^3, where
       f = slipperiness of the block 1 below bot.entity.position * 0.91. Slipperiness:
       0.6; slime block 0.8; ice, packed ice, frosted ice 0.98; blue ice 0.989. The speed
       attribute
       is bot.entity.attributes['generic.movement_speed'] as the server sent it (its value
       with its modifiers), or 0.1 when the server sent none. sprint held: the attribute
       is multiplied by 1.3 (bot.physics.sprintSpeed 0.3). On a 0.6 block with attribute
       0.1 the acceleration is 0.1, with sprint 0.13.
     in the air: 0.02; with sprint held 0.026.
  5. On a ladder (see below): horizontal velocity is limited to 0.15 each way, and the
     fall to 0.15 a tick; with sneak held velocity.y is not below 0 (the body holds).
  6. The body moves by its velocity and collides: guide("physics-collision").
  7. On a ladder, when the move was blocked sideways or jump is held: velocity.y = 0.2
     (climbs 0.2 blocks a tick, less gravity).
  8. Gravity: velocity.y minus 0.08, then times 0.98. With Slow Falling and velocity.y at
     or below 0: minus 0.01. With Levitation: velocity.y moves a fifth of the way to 0.05
     * level instead of the gravity. The fastest fall is 3.92 blocks a tick.
  9. Horizontal velocity times f on the ground (0.546 on a 0.6 block), times 0.91 in the
     air.

Steady speeds on a 0.6 block with speed attribute 0.1, in blocks a second.
  forward 4.32; forward with sprint 5.61; forward with sneak 1.30.

The keys one by one.
  forward, back, left, right     the input of step 3; they act in the air too (step 4)
  jump       step 2; on a ladder step 7; in water and lava it adds 0.04 a tick upward
  sprint     speed attribute times 1.3 on the ground, 0.026 instead of 0.02 in the air,
             0.2 more forward at a jump. It acts with any direction key. The simulation
             tests neither food nor the forward key for it. No effect in water or lava.
  sneak      input times 0.3; on the ground the body does not move past an edge
             (guide("physics-collision")); holds on a ladder; no bounce on a slime block

A ladder is: the block at the feet is a ladder, a vine, a scaffolding, or an open
trapdoor directly above a ladder that faces the same way as the ladder.
