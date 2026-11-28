guide("entity-object"): every field and method of an Entity object.

An Entity is one object per entity id. bot.entities holds it under its id and the same
object is changed in place as packets arrive. Which packet fills which field:
guide("entity-updates"). The values of name, type and kind: guide("entity-names").

Fields every Entity has from the moment it is created.
  entity.id                number, the server's entity id
  entity.position          Vec3, the feet (bottom centre of its box). A player's box is
                           0.6 wide and 1.8 high: it fills two cells, the one of the
                           feet and the one above it, and its eyes are 1.62 above
                           position; starts at (0, 0, 0);
                           the same Vec3 object is changed in place as the entity moves
  entity.velocity          Vec3, blocks per tick; starts at (0, 0, 0); changed in place
  entity.yaw               radians; 0 faces -z, PI/2 faces -x, PI faces +z; starts at 0
  entity.pitch             radians; positive is up, negative is down; starts at 0
  entity.onGround          boolean; starts true. For bot.entity the physics sets it every
                           tick. For every other entity nothing changes it: it stays true.
  entity.height            number of blocks; starts at 0
  entity.width             number of blocks; starts at 0
  entity.effects           object keyed by effect id: { id, amplifier, duration }; starts {}
  entity.equipment         array; index 0 main hand, 1 off hand, 2 boots, 3 leggings,
                           4 chestplate, 5 helmet; each entry an Item, null, or undefined
                           when the server has sent nothing for that slot
  entity.heldItem          read-only; the same value as entity.equipment[0]
  entity.metadata          array indexed by metadata key, raw values as the server sent
                           them; starts []
  entity.isValid           boolean; starts true; false once the server removed the entity
  entity.passengers        array of Entity riding this one; starts []
  entity.vehicle           the Entity this one rides, or null; starts null

Fields set when the server announces the entity. Undefined before that.
  entity.type              string, see guide("entity-names")
  entity.name              string, for example 'zombie', 'item', 'player'
  entity.displayName       string, for example 'Zombie'; undefined for players and orbs
  entity.entityType        number, the entity type id; undefined for players and orbs
  entity.kind              string, the category; undefined for players and orbs
  entity.uuid              string; undefined for experience orbs
  entity.username          string; players only
  entity.eyeHeight         number; players only: 1.62, or 1.27 while crouching
  entity.count             number, the amount of experience; experience orbs only
  entity.headPitch         radians; set once, when a living entity is announced
  entity.dataBlobs         players only; undefined on 1.16.1

Fields set by later packets. Undefined until the first such packet.
  entity.headYaw           radians, same scale as yaw
  entity.attributes        object keyed by attribute name:
                           { value, modifiers: [{ uuid, amount, operation }] }
  entity.crouching         boolean; true or false after a metadata packet with the flags
  entity.elytraFlying      boolean; true or false after a metadata packet with the flags

Fields the type declaration lists and no code fills: entity.health, entity.food,
entity.foodSaturation, entity.player. They are undefined on every entity, bot.entity
included. The bot's own values are bot.health, bot.food, bot.foodSaturation, bot.player.

entity.mobType, entity.objectType
  Deprecated. Reading either returns entity.displayName and prints a stack trace with
  'Warning: entity.mobType is deprecated. Use entity.displayName instead' (or objectType).
  Writing either sets entity.displayName and prints the same warning.

entity.setEquipment(index, item)
  Sets entity.equipment[index] = item. Sends nothing.

entity.getCustomName() -> ChatMessage | null
  Returns null when entity.metadata[2] is undefined. Otherwise returns
  ChatMessage.fromNotch(entity.metadata[2]).

entity.getDroppedItem() -> Item | null
  Returns null when entity.name is not 'item'. Otherwise returns
  Item.fromNotch(entity.metadata[7]): an Item, or null when the stack is marked absent.
  Throws TypeError "Cannot read properties of undefined (reading 'present')" when
  entity.metadata[7] is undefined, which is the case from the 'entitySpawn' event of a
  dropped item until its first metadata packet ('itemDrop' is emitted at that packet).

An Entity is also a Node EventEmitter (on, once, emit). The library emits nothing on it.
