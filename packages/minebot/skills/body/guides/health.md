guide("health"): health, food, death, respawn and the 'spawn' event.

bot.health                           number, 0 to 20 (half hearts); undefined before the
                                     first health packet
bot.food                             number, 0 to 20; undefined before the first packet
bot.foodSaturation                   number; undefined before the first packet
  All three are set from each health packet of the server and at no other time. Writing
  them changes nothing on the server.

bot.isAlive                          boolean, true at creation
  false from a health packet with health at or below 0, and from every respawn packet
  (after death, and at every change of dimension). true again at the next health packet
  with health above 0.

At each health packet, in this order.
  1. bot.health, bot.food, bot.foodSaturation are set.
  2. 'health' is emitted.
  3. Health at or below 0: when bot.isAlive is true it becomes false and 'death' is
     emitted. Then, with the createBot option respawn true (the default), bot.respawn()
     is called. This repeats at every health packet with health 0 or less.
  4. Health above 0 while bot.isAlive is false: bot.isAlive becomes true and 'spawn' is
     emitted.

bot.respawn()
  Synchronous; returns undefined.
  bot.isAlive true: it returns at once and sends nothing.
  bot.isAlive false: it sends one client-command packet with actionId 0 (perform
  respawn). It changes no field and does not wait for the server. bot.isAlive is false
  after a death, and also between the respawn packet of a change of dimension and the
  next health packet; a call in either time sends the packet.
  When the server then sends a respawn packet, 'respawn' is emitted; at its next health
  packet with health above 0, bot.isAlive becomes true and 'spawn' is emitted.

The createBot option respawn (default true; null or undefined counts as true).
  true: the library calls bot.respawn() itself at every health packet with health 0 or
  less, right after 'death' (step 3 above).
  false: nothing in the library calls bot.respawn(). After a death bot.isAlive stays
  false and the body stays dead until code calls bot.respawn().
  The bot of this body is created with respawn: false; what the body does at death and
  for a respawn: guide("run-death").

Events.
  'health' ()      at every health packet, also when the numbers are the same as before
  'death' ()       once when health reaches 0 or less while bot.isAlive was true
  'respawn' ()     at every respawn packet from the server: after a death, and at every
                   change of dimension. bot.isAlive is false from here.
  'spawn' ()       at the first health packet the bot receives, when its health is above
                   0; and at each health packet with health above 0 while bot.isAlive
                   was false: after a respawn and after a change of dimension.

What death does to the body in other modules.
  At 'death' the simulation stops (guide("tick-loop")). It starts again 1.5 s after the
  server's position packet that follows the respawn (guide("physics-server-sync")).
  The movement keys keep their state through death and respawn.
