guide("control-keys"): the seven movement keys: setting, reading and releasing them.

The keys.
  forward, back, left, right, jump, sprint, sneak. Each is true (held) or false. All
  are false when the bot is created. A key stays as it was set until it is set again;
  nothing in this module releases a key (not death, not a teleport, not mounting).
  What a held key does to the body at each tick: guide("physics-keys"), and in water and
  lava guide("physics-liquid").
  forward, back, left and right move the body relative to the yaw of the head
  (bot.entity.yaw, guide("look")): forward is along (-sin(yaw), -cos(yaw)) in (x, z), back
  the opposite, left and right at a right angle to it. A turn of the head changes the
  direction of the keys held from the next tick. No plugin presses the keys: they are
  held only as code sets them.

Channel.
  setControlState and clearControlStates use the channel move (guide("run-channels")):
  code that did not say it uses move gets the error 'setControlState uses the channel
  move: this code said it uses ...' and no key changes. getControlState and reading
  bot.controlState use no channel. Writing bot.controlState.KEY goes to the bot's own
  setControlState, not the gated one: it is not checked against the channels, not
  recorded for the run, and acts also while the run is paused. When the head is turned by code on another
  channel (look), the code on move reads bot.entity.yaw to know where its keys move the
  body.
  When the job on move is paused or ends, the body calls bot.clearControlStates(): every
  key is up. At its resume the keys it recorded as held are pressed again
  (guide("run-pause")).

bot.setControlState(control, state)
  control: one of the seven names (string). state: true or false (boolean).
  1. Throws an AssertionError 'invalid control: <control>' when control is not one of the
     seven names.
  2. Throws an AssertionError 'invalid state: <state>' when state is not a boolean.
  3. Returns at once when the key already has that state: nothing is sent.
  4. Stores the state. Then, by key:
     jump, state true: sets bot.jumpQueued = true.
     sprint: sends an entity_action packet to the server, 'start sprinting' for true,
       'stop sprinting' for false.
     sneak: sends an entity_action packet, 'start sneaking' for true, 'stop sneaking'
       for false.
     forward, back, left, right, and jump set to false: nothing is sent.
  Returns undefined. It does not wait. The simulation reads the stored keys at its next
  tick (every 50 ms).

bot.getControlState(control) -> boolean
  The stored state of the key. Throws an AssertionError 'invalid control: <control>' for
  another name.

bot.clearControlStates()
  Calls bot.setControlState(key, false) for all seven keys. Returns undefined.

bot.controlState
  An object with the seven keys as properties. Reading bot.controlState.forward returns
  the stored state. Writing bot.controlState.forward = true calls
  bot.setControlState('forward', true), with the same checks and errors.

bot.jumpQueued                       boolean, false at creation
  Set to true by bot.setControlState('jump', true). The next simulation tick treats it as
  the jump key held for that one tick, then sets it to false. A jump key pressed and
  released between two ticks therefore still gives one jump attempt.

bot.jumpTicks                        number, 0 at creation
  Ticks left before the simulation allows another jump from the ground. Set to 10
  (bot.physics.autojumpCooldown) at each jump from the ground. While the jump key is held
  it goes down by 1 a tick. At a tick with the jump key not held it is set to 0. A
  position packet from the server (a teleport) sets it to 0.
