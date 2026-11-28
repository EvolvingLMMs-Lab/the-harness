guide("entity-updates"): which server packet changes which Entity field, and when.

Every packet that names an entity id not yet in bot.entities creates a new Entity for
that id with the starting values of guide("entity-object") and stores it in bot.entities.
The event each packet emits is in guide("entity-events").

Appearing.
  A player comes into view: type 'player', name 'player', username, uuid, position, yaw,
    pitch, eyeHeight 1.62, height 1.8, width 0.6. If bot.players[username] exists and has
    no entity, its entity field is set to this Entity. The packet is ignored (no Entity
    fields set, no event) when the player's uuid is not in bot.uuidToUsername.
  A living entity appears: type, displayName, entityType, name, kind, height, width from
    the game data, uuid, position, yaw, pitch, headPitch, velocity.
  A non-living entity appears (item, arrow, boat and so on): the same fields without
    headPitch.
  An experience orb appears: type 'orb', name 'experience_orb', width 0.5, height 0.5,
    position, count.

Moving.
  Relative move: position is shifted by the packet's step (1/4096 block units).
  Look: yaw and pitch. Move and look: both. Teleport: position, yaw and pitch replaced.
  Head rotation: headYaw.
  Velocity packet: velocity = packet value / 8000, in blocks per tick. Between velocity
    packets the library does not change another entity's velocity or position by itself.
  Angles arrive as 1/256 of a turn. yaw = (PI - degrees) mod 2 PI, pitch = -degrees, both
    in radians.
  These packets do not change entity.onGround.

State.
  Equipment packet: entity.equipment[slot] = Item or null for each slot listed.
  Entity status 55: equipment[0] and equipment[1] are swapped.
  Metadata packet: each listed key replaces entity.metadata[key]; other keys stay.
    Key 0 holds flag bits. Bit 0x02 set: entity.crouching = true, eyeHeight = 1.27,
    height = 1.5. Bit 0x02 clear while crouching is true: crouching = false,
    eyeHeight = 1.62, height = 1.8. These height changes are applied to any entity type.
    Bit 0x80 set: entity.elytraFlying = true. Clear while it is true: false.
    For bot.entity only, key 1 sets bot.oxygenLevel = round(value / 15) and emits 'breath'.
  Effect packet: entity.effects[id] = { id, amplifier, duration } (duration as sent, in
    ticks; it does not count down in the object).
  Effect removal packet: deletes entity.effects[id].
  Attributes packet: entity.attributes[key] = { value, modifiers } for each listed key;
    other keys stay.

Riding.
  Passenger packet (vehicle id, list of passenger ids): for each listed passenger, it is
    removed from the passengers array of its previous vehicle, passenger.vehicle = the
    vehicle Entity, and it is pushed onto vehicle.passengers. A passenger that is no
    longer in the list keeps its vehicle field and stays in the old passengers array.
    When the vehicle id is not in bot.entities, passenger.vehicle becomes undefined.
  Attach packet (entity id, vehicle id): with vehicle id -1, entity.vehicle = null. With
    another id, entity.vehicle = that Entity and the entity is pushed onto its passengers
    array; if the entity was not already in that array, the array's last element is
    removed first.

Disappearing.
  Destroy packet, for each id: 'entityGone' is emitted, then entity.isValid = false, then
    bot.players[entity.username].entity = null when the entity has a username and that
    player is listed, then the id is deleted from bot.entities. The Entity object keeps
    its last field values. Its vehicle, its passengers and bot.vehicle are not changed.
  On each login packet bot.entities is replaced by an empty object and bot.entity is a new
    Entity.
