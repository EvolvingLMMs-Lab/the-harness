guide("look"): turning the head: bot.look, bot.lookAt, yaw and pitch, the turning speed.

Yaw and pitch.
  bot.entity.yaw and bot.entity.pitch are in radians.
  yaw 0 faces -z (north), PI/2 faces -x (west), PI faces +z (south), 3*PI/2 faces +x
  (east). The facing direction is (-sin(yaw), -cos(yaw)) in (x, z).
  pitch 0 is level, PI/2 is straight up, -PI/2 is straight down.
  The server's angles are degrees: server yaw = (PI - yaw) * 180 / PI, server pitch =
  -pitch * 180 / PI.

Channel.
  bot.look and bot.lookAt use the channel look (guide("run-channels")): code that did not
  say it uses look gets the error 'look uses the channel look: this code said it uses
  ...' and the head does not turn. bot.dig, placeBlock, placeEntity, activateBlock,
  activateEntity, activateEntityAt and openBlock turn the head too and use look with use.
  Reading bot.entity.yaw and pitch uses no channel.
  The yaw sets the direction of the movement keys (guide("control-keys")): a turn made by
  code on look changes where the keys held by code on move take the body, from the next
  tick. When the job on look is paused or ends, the head stays where it is.

bot.look(yaw, pitch, force) -> Promise
  yaw, pitch: numbers, radians. force: boolean, default undefined (false).
  1. A bot.look still pending from an earlier call resolves now.
  2. The change from bot.entity.yaw to yaw, and from bot.entity.pitch to pitch, is each
     rounded to a whole multiple of 0.15 degrees (0.002618 rad). The yaw change is the
     plain difference yaw - bot.entity.yaw: it is not shortened to the nearer way round,
     and bot.entity.yaw can leave the range 0 to 2*PI.
  3. Both rounded changes 0: resolves at once, nothing changes.
  4. Adds the changes to bot.entity.yaw and bot.entity.pitch at once. The simulation
     walks along bot.entity.yaw from its next tick on.
  5. force true: the turn is marked as already sent in full, and the promise resolves at
     once. The next position update (next tick, 50 ms) carries the full new yaw and
     pitch to the server.
  6. force false: the yaw and pitch sent to the server follow bot.entity.yaw and
     bot.entity.pitch by at most 0.15 rad (8.6 degrees) a tick each
     (bot.physics.yawSpeed * 0.05 and bot.physics.pitchSpeed * 0.05). A half turn (PI)
     takes 21 ticks. The promise resolves at the first 'move' event at which the sent yaw
     is within 0.001 rad of bot.entity.yaw. The pitch is not part of that test.
  It has no time limit and does not reject. With force false it stays pending for as
  long as no position update is sent: while the body is mounted, while it is dead, before
  the first position packet from the server, and while the chunk under it is not loaded.

bot.lookAt(point, force) -> Promise
  point: Vec3. force: as in bot.look.
  Takes the vector from the eyes (bot.entity.position raised by bot.entity.eyeHeight,
  1.62) to point, computes yaw = atan2(-dx, -dz) and pitch = atan2(dy, sqrt(dx*dx +
  dz*dz)), and awaits bot.look(yaw, pitch, force). Resolves and stays pending as bot.look
  does.

bot.physics.yawSpeed                 3.0 radians a second: the limit in step 6
bot.physics.pitchSpeed               3.0 radians a second
  Writing a new number changes the limit from the next tick.

Yaw and pitch set by the server.
  A position packet from the server sets bot.entity.yaw and bot.entity.pitch (absolute,
  or added to the current ones, as the packet's flags say) and marks them as sent.
  See guide("physics-server-sync").
