guide("elytra"): bot.elytraFly, the elytra flight in the simulation, firework boosts.

bot.elytraFly() -> Promise
  Checks, in this order, and rejects at the first that holds:
    bot.entity.elytraFlying is true        'Already elytra flying'
    bot.entity.onGround is true            'Unable to fly from ground'
    bot.entity.isInWater is true           'Unable to elytra fly while in water'
    the Levitation effect is on the body   'Unable to elytra fly with levitation effect'
    the chest slot (bot.inventory.slots[6]) is empty or holds an item whose name is not
    'elytra'                               'Elytra must be equip to start flying'
  Then sends an entity_action packet 'start fall flying' and resolves with undefined at
  once. It does not wait for the server. It does not set bot.entity.elytraFlying.

bot.entity.elytraFlying
  Set from the entity data the server sends for the body: true when the server's flag for
  elytra flight is set, false when it is cleared. 'entityElytraFlew' (entity) is emitted
  when it turns true.
  At every tick the simulation sets it to false unless all of these hold: it was true,
  slots[6] holds an 'elytra', bot.entity.onGround was false, no Levitation. It also sets
  it to false when the flight's move ends on the ground.

One tick of flight (out of water and lava; the keys forward, back, left, right have no
effect; cp = cos(pitch), look = the unit vector of yaw and pitch, h = horizontal speed).
  1. velocity.y += 0.08 * (-1 + 0.75 * cp * cp). Level: -0.02 a tick. Straight up or
     down: -0.08. With Slow Falling while velocity.y is 0 or less: an eighth of it.
  2. Falling (velocity.y < 0): m = -0.1 * velocity.y * cp * cp is added to velocity.y,
     and m along the horizontal look direction: falling turns into forward speed.
  3. Looking up (pitch > 0): m = 0.04 * h * sin(pitch); 3.2 * m is added to velocity.y,
     and m is taken from the speed along the horizontal look direction: forward speed
     turns into height.
  4. The horizontal velocity moves 0.1 of the way to (h along the look direction): the
     flight turns with the head.
  5. velocity.x and z times 0.99, velocity.y times 0.98. Then the body moves and
     collides. On the ground: elytraFlying = false.
  In water or lava the liquid rules run in place of these.

Firework boost.
  bot.fireworkRocketDuration   number, 0 at creation: ticks of boost left.
  It is set when the server shows a firework rocket entity attached to the body:
  10 * (flight + 1) plus a random 0 to 11 ticks, where flight is the Flight value of the
  rocket item (1 when absent). 'usedFirework' (fireworkEntityId) is emitted then, once
  for each rocket entity.
  At each tick with the number above 0: while elytraFlying is true, each velocity
  component v becomes v + look * 0.1 + (look * 1.5 - v) * 0.5 and the number goes down
  by 1; while elytraFlying is false the number is set to 0.
  It is also set to 0 when the server clears the body's elytra flag.
