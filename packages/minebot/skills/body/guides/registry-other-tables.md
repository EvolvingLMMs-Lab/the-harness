guide("registry-other-tables"): language, attributes, instruments, particles and the rest.

bot.registry.language
  Object: translation key -> English text with %s places. 4754 keys.
    language['chat.type.text']             -> '<%s> %s'
    language['block.minecraft.stone']      -> 'Stone'
    language['death.attack.mob']           -> '%1$s was slain by %2$s'
  ChatMessage.toString() reads it to turn a translated message into text.

bot.registry.attributes[resource], bot.registry.attributesByName[name],
bot.registry.attributesArray
  13 records: { name, resource, default, min, max }.
  As resource (name) default, min to max:
    generic.max_health (maxHealth) 20, 1 to 1024
    generic.follow_range (followRange) 32, 0 to 2048
    generic.knockback_resistance (knockbackResistance) 0, 0 to 1
    generic.movement_speed (movementSpeed) 0.7, 0 to 1024
    generic.attack_damage (attackDamage) 2, 0 to 2048
    generic.attack_speed (attackSpeed) 4, 0 to 1024
    generic.attack_knockback (attackKnockback) 0, 0 to 5
    generic.flying_speed (flyingSpeed) 0.4, 0 to 1024
    generic.armor (armorHealth) 0, 0 to 30
    generic.armor_toughness (armorToughness) 0, 0 to 20
    generic.luck (luck) 0, -1024 to 1024
    horse.jump_strength (horseJumpStrength) 0.7, 0 to 2
    zombie.spawn_reinforcements (zombieSpawnReinforcements) 0, 0 to 1

bot.registry.instruments[id], bot.registry.instrumentsArray
  16 records { id, name }, the instruments of note blocks: 0 harp, 1 basedrum, 2 snare,
  3 hat, 4 bass, 5 flute, 6 bell, 7 guitar, 8 chime, 9 xylophone, 10 iron_xylophone,
  11 cow_bell, 12 didgeridoo, 13 bit, 14 banjo, 15 pling.

bot.registry.particles[id], bot.registry.particlesByName[name],
bot.registry.particlesArray
  72 records { id, name }, ids 0 to 71: 0 ambient_entity_effect, 3 block, 6 crit,
  14 dust, 22 explosion, 26 flame, 32 heart, 34 item, 38 lava, 42 portal, 44 smoke, ...
  The id is particle.id of the 'particle' event.

bot.registry.mapIcons[id], bot.registry.mapIconsByName[name], bot.registry.mapIconsArray
  27 records { id, name, appearance, visibleInItemFrame }: 0 player, 1 frame,
  2 red_marker, 3 blue_marker, 4 target_x, 5 target_point, 6 player_off_map,
  7 player_off_limits, 8 mansion, 9 monument, 10 to 25 banner_<colour>, 26 red_x.

bot.registry.tints
  { grass, foliage, water, redstone, constant }. Each is { data, default }: data is an
  array of { keys, color }, default a colour number. For grass, foliage and water the
  keys are biome names; for redstone they are power levels 0 to 15; for constant they
  are block names (birch_leaves, spruce_leaves, lily_pad).

bot.registry.commands
  { root, parsers }: the command tree of the game. root.children holds 74 nodes, one for
  each command name (advancement, attribute, ..., tp, weather, xp). A node is
  { type: 'literal' or 'argument', name, executable, redirects, children }; an argument
  node also names its parser. parsers lists { parser, modifier, examples }.
  The table is the same for every server.

bot.registry.loginPacket
  A sample login packet with the fields entityId, gameMode, previousGameMode,
  worldNames, dimensionCodec, dimension, worldName, hashedSeed, maxPlayers,
  viewDistance, reducedDebugInfo, enableRespawnScreen, isDebug, isFlat. The packet the
  server sent is not stored here.

bot.registry.protocol        { types, handshaking, status, login, play }: the packet
                             definitions the connection uses
bot.registry.protocolYaml    [path of the protocol description file, undefined]
