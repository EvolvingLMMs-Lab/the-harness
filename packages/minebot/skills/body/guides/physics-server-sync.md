guide("physics-server-sync"): how the body's position and look are sent to the server, the
'move' event, and what a position packet from the server (a teleport) does.

Sending, once at each tick while physics is on (guide("tick-loop")).
  1. Nothing is sent from the 20th tick on after bot.isAlive became false, until it is
     true again. Nothing is sent while bot.entity.position.x is not a finite number.
  2. The yaw and pitch to send move toward bot.entity.yaw and bot.entity.pitch by at most
     0.15 rad each (guide("look")).
  3. One packet is chosen:
     position and look: the position differs from the last one sent, or 1000 ms have
       passed since the last position was sent; and the look differs from the last sent.
     position: the position condition alone.
     look: the look differs alone.
     on-ground flag alone: nothing else changed and bot.entity.onGround differs from the
       last flag sent.
     none: nothing changed.
     Each packet carries bot.entity.onGround.
  So a body that stands still sends its position once a second.

'move' (oldPosition)
  Emitted right after each position packet, look packet, and position-and-look packet is
  sent; not for the on-ground flag alone. oldPosition is a Vec3: the position that was
  last sent before this packet. bot.entity.position is the new one. The event comes for
  a turn of the head without a change of position, and once a second while standing.

A position packet from the server (the server sets where the body is). In this order:
  1. bot.entity.height = 1.8.
  2. For x, y and z the packet says absolute or relative. Absolute: the coordinate is
     set and that component of bot.entity.velocity becomes 0. Relative: the number is
     added to the coordinate and the velocity component stays.
  3. bot.entity.yaw and bot.entity.pitch are set, absolute or added, the same way.
  4. bot.entity.onGround = false.
  5. A teleport_confirm packet with the packet's teleportId is sent.
  6. A position-and-look packet with the new position is sent ('move' is emitted),
     physics is turned on, bot.jumpTicks = 0, the look counts as sent, and 'forcedMove'
     is emitted.
     When the packet arrives less than 2000 ms after a 'death' event, step 6 is done
     1500 ms later instead, for the first such packet after that death. During the
     1500 ms the body is not simulated.
  The keys are not changed. A key held before the packet is still held after it.

'forcedMove' ()
  Emitted at the end of step 6. bot.entity.position is then the position the server set.

pulled_back
  At each 'forcedMove' the body notes the event pulled_back {position}: the position the
  server set, 2 decimals. The server sends a position packet when it does not accept a
  move the body sent (the body is put back where the server has it), and at a teleport,
  a respawn and a change of dimension. The event is counted in `did.pulled_back` of the
  running job that holds the channel move (guide("run-report")); with no job on move it
  is noted and not counted. The keys stay held (step 6), so a key that moved the body
  into a place the server refuses moves it there again at the next tick.
