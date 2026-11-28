guide("mount-riding"): bot.mount, bot.dismount, bot.moveVehicle, bot.vehicle, riding events.

bot.mount(target)
  target is an Entity. Synchronous, returns undefined. Sends one interact packet for
  target.id with the main hand and the bot's sneak control state
  (bot.getControlState('sneak')); the same packet as bot.useOn(target). It turns no
  head, checks no distance and waits for nothing. Whether the bot ends up riding is
  reported by the 'mount' event. Throws TypeError when target is null or undefined.

bot.vehicle
  The Entity the bot rides. Undefined until the first 'mount'. Set just before 'mount'
  is emitted, to bot.entities[vehicle id]. Set to null just before 'dismount' is
  emitted. No other code changes it: when the vehicle entity is removed by the server
  (entity.isValid false) bot.vehicle keeps pointing at it and no 'dismount' is emitted.

'mount'
  No arguments; the vehicle is bot.vehicle. Emitted when
  - a passenger packet lists the bot's entity id among the passengers of a vehicle, or
  - an attach packet names the bot's entity id with a vehicle id other than -1.
  Emitted again each time such a packet arrives, also while already riding.

'dismount' (vehicle)
  vehicle is the previous bot.vehicle. Emitted when an attach packet names the bot's
  entity id with vehicle id -1, or a passenger packet with vehicle id -1 lists the bot.
  A passenger packet for the bot's vehicle that no longer lists the bot emits nothing
  and leaves bot.vehicle and bot.entity.vehicle as they were.

bot.dismount()
  Synchronous, returns undefined.
  When bot.vehicle is truthy: sends one steer packet with sideways 0, forward 0 and the
  flags byte 0x02. It waits for nothing and does not change bot.vehicle.
  When bot.vehicle is falsy: sends nothing and emits 'error' on bot with
  Error('dismount: not mounted'). It does not throw.

bot.moveVehicle(left, forward)
  Synchronous, returns undefined. Sends one steer packet with sideways = left,
  forward = forward and the flags byte 0x01. Both numbers are sent as given (32-bit
  floats); positive left is left, negative is right; positive forward is forward,
  negative is backward. One call is one packet; nothing repeats it. It does not check
  bot.vehicle.

Passengers of any entity: entity.vehicle and entity.passengers, guide("entity-updates").
Events about other entities: 'entityAttach' (entity, vehicle) and 'entityDetach'
(entity, vehicle), guide("entity-events").
