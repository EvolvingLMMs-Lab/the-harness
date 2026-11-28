guide("explosion"): what an explosion packet changes, and bot.getExplosionDamages.

When the server reports an explosion.
  The packet holds the centre, a radius, a list of destroyed block positions and a push
  for the bot.
  Blocks: each listed position is set to air (state 0) in the bot's copy of the world at
    once. A painting recorded at a position whose block type changed is forgotten.
  Push: the packet's push vector is added to bot.entity.velocity (blocks per tick) when
    bot.physicsEnabled is true and bot.game.gameMode is not 'creative'. Otherwise the
    velocity is not changed.
  No explosion event is emitted on bot, and the centre and radius are not stored.

bot.getExplosionDamages(targetEntity, sourcePos, power, rawDamages = false)
    -> number | null
  A local calculation; it sends nothing. targetEntity is an Entity, sourcePos a Vec3
  (the centre of the explosion), power a number.
  1. distance = from targetEntity.position (the feet) to sourcePos; radius = 2 * power.
     distance >= radius: returns 0.
  2. exposure = the share, 0 to 1, of sample points of a box 0.6 x 1.8 x 0.6 standing on
     targetEntity.position (a grid with steps 0.6 / 2.2 across and 1.8 / 4.6 up) from
     which a ray to sourcePos meets no block in the bot's copy of the world. The box has
     the size of a standing player whatever the entity is.
  3. impact = (1 - distance / radius) * exposure
     damage = floor((impact * impact + impact) * 7 * power + 1)
  4. rawDamages true: returns damage.
  5. rawDamages false: reads targetEntity.attributes['generic.armor'].
     Absent: returns null.
     Present: armor and toughness are the values of the attributes 'generic.armor' and
     'generic.armorToughness' with their modifiers applied (operation 0 added to the
     base, operation 1 adding base * amount, operation 2 multiplying by 1 + amount), and
       damage = damage * (1 - min(20, max(armor - damage / (2 + toughness / 4),
                                          armor * 0.2)) / 25)
     When targetEntity.type is 'player' the result is multiplied by 0.5 times the
     difficulty number of bot.game.difficulty: 'peaceful' 0, 'easy' 1, 'normal' 2,
     'hard' 3. Returns floor(damage).
  Enchantments and potion effects are not part of the calculation.
  Throws TypeError when rawDamages is false and targetEntity.attributes is undefined (no
  attributes packet has arrived for that entity), or when 'generic.armor' is present and
  'generic.armorToughness' is absent.
