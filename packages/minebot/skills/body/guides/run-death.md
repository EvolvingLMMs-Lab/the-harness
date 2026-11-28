guide("run-death"): what the body does when it dies, while it is dead, and for a respawn.

At death.
  Mineflayer emits 'death' when a health packet has health 0 or less while bot.isAlive is
  true, and sets bot.isAlive to false. The bot is made with the option respawn: false, so
  Mineflayer sends no respawn request by itself (guide("health")).
  The body notes the event death {position, message}: `position` is where the body's
  entity is, `message` is the last chat line of the 1500 ms before that begins with the
  body's name and a space, or null when there is none.
  The bridge then adds one to `deaths` and tells every running job and every paused job
  to stop, with the cause death (guide("run-ending")).
  The game makes a new player at the respawn and sends nothing about what the dead one
  had. So at the death the body drops from its picture the window that was open
  (bot.currentWindow becomes null, 'windowClose' is emitted, the event window {open: false}
  is noted) and the effects (bot.entity.effects becomes {}).

While dead.
  The state has dead: true (bot.isAlive is false) and the health the game sent.
  A run that is started is refused before any line of it runs: status 'error', error
  'the body is dead: no code runs on it until respawn()'.
  Saving and reading routines, defining senses and chat() work as before. Senses are
  computed as before.
  Mineflayer emits no physics tick while the body is dead: the state's `ticks` stands
  still. The 8-second rule of guide("run-restart") does not run while the state has
  dead: true: the body stays dead, in the same process, until respawn().

respawn()
  Respawn when you want the body back, not at the moment it dies. A dead body waits for
  as long as you take: nothing ends, nothing is lost by waiting. Do not call respawn()
  at once on death: the body would stand at its spawn point again before you have seen
  how it died and decided what to do.
  The Python call. In this order:
  - It is called by a reflex's program (the node's own function, or anything that
    function calls): it raises "Nothing was sent: respawn() is called by your own
    program, not by a reflex's ...". Nothing is sent to the body.
  - The body is not in the world, or has sent no state:
    {respawned: False, dead: None, why: 'the body is not in the world'}.
  - The last state has dead false: {respawned: False, dead: False, why: 'the body is
    alive'}.
  - Otherwise the body calls bot.respawn() when bot.isAlive is false: Mineflayer sends
    the game the client command with actionId 0 (the respawn request). An error is noted
    as the event error {message: 'respawn: ...'}.
  - The bridge then reads the state every 100 ms, 100 times at most (10 seconds), until
    dead is false, and answers {respawned, dead}: respawned is True when dead turned
    false in that time.
  When the game answers with a health packet above 0, Mineflayer sets bot.isAlive to
  true and emits 'spawn'; the body notes respawn_or_dimension {dimension}.

bot.respawn()
  Mineflayer's call that sends the respawn request: guide("health"). On the bot given to
  code it is the bot's own function (not gated).
