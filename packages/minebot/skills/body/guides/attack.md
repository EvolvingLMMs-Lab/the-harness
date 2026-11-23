guide("attack"): bot.attack and bot.swingArm, hitting an entity.

bot.attack(target, swing = true)
  target is an Entity. The call is synchronous and returns undefined.
  1. Sends one attack packet for target.id. The packet carries the bot's sneak control
     state (bot.getControlState('sneak')).
  2. When swing is true, calls bot.swingArm() (right arm).
  It turns no head, checks no distance, checks no line of sight, does not check
  target.isValid, and waits for no answer. Nothing in the call reports whether the hit
  landed; the 'entityHurt' (entity) event is emitted when the server reports the hurt.
  Throws TypeError when target is null or undefined.
  The game counts the hit when the target's position is less than 6 blocks from the
  body's position. Both are entity.position, the point at the feet, and the distance is
  taken in all three directions. The game gives a hit its full strength 0.625 seconds
  after the last one with a sword, 1 to 1.25 seconds with an axe, 0.25 seconds with a
  bare hand.

bot.swingArm(arm = 'right', showHand = true)
  Sends one arm animation packet and returns undefined. arm 'right' is the main hand;
  any other value is the off hand. With showHand false the packet is sent without a hand
  value, which goes out as the main hand.

bot.entityAtCursor(maxDistance = 3.5) -> Entity | null
  The entity the bot's view ray hits first: guide("entity-find").

Events after a hit, all on bot: 'entityHurt' (entity), 'entityDead' (entity),
'entityGone' (entity), 'entityCriticalEffect' (entity): guide("entity-events").
