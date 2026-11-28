guide("tick-loop"): the physics tick: when it runs, when it stops, bot.physicsEnabled, the
'physicsTick' event.

The timer.
  At the 'login' event a timer starts that fires every 50 ms. It is stopped at the 'end'
  event. Each firing adds the real time since the last firing to a store and runs one
  tick for every 0.05 s in the store, at most 4 ticks in one firing (the createBot option
  maxCatchupTicks, default 4). Time left over stays in the store. After a pause of the
  process the ticks are caught up 4 at a firing.

One tick.
  1. Nothing happens, and no event is emitted, when one of these holds:
     the connection is not in the play state;
     bot.entity has no position, or its x is not a finite number;
     the block at bot.entity.position is not loaded (bot.blockAt returns null).
  2. When bot.physicsEnabled is true and physics is on (see below): the simulation moves
     the body one tick from the keys (guide("physics-keys")), writes the result to
     bot.entity (guide("physics-state")), then emits 'physicsTick' and after it
     'physicTick'.
  3. When physics is on: the position and the look are sent to the server
     (guide("physics-server-sync")).

Physics on and off (kept inside the module; not readable).
  Off at 'login'. Off at 'mount', at 'death', and at 'respawn' (a respawn packet: after
  death and at every change of dimension).
  On when a position packet arrives from the server (the packet with which the server
  sets where the body is). After 'death' the switch to on comes 1.5 s after that packet:
  guide("physics-server-sync").
  The 'dismount' event does not turn it on. After a dismount the body is simulated again
  from the next position packet from the server.
  While it is off the body is not simulated, no position is sent, 'physicsTick' is not
  emitted, and a bot.look without force stays pending.

bot.physicsEnabled                   boolean; true unless createBot got physicsEnabled
  Writing false stops step 2 from the next tick: the body is not simulated and
  'physicsTick' is not emitted. Step 3 goes on: bot.entity.position, yaw and pitch, as
  code writes them, are sent to the server. Writing true starts step 2 again.

Events.
  'physicsTick' ()     after each simulated tick (step 2), 20 a second
  'physicTick' ()      the same moment, after 'physicsTick'. Adding a listener for it
                       prints a console warning that the name is deprecated.

Explosions.
  At an explosion packet, when bot.physicsEnabled is true and bot.game.gameMode is not
  'creative', the packet's push (playerMotionX, playerMotionY, playerMotionZ) is added to
  bot.entity.velocity.

Waiting for ticks: guide("tick-wait").
