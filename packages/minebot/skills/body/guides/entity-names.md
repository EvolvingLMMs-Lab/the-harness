guide("entity-names"): the values of entity.name, entity.type and entity.kind on 1.16.1.

entity.type
  'player'    another player, and bot.entity
  'orb'       an experience orb
  'UNKNOWN'   bee, hoglin, piglin, strider, zoglin, zombified_piglin
  'mob'       every other entity in the lists below: monsters and animals, and also
              dropped items, arrows, boats, minecarts, falling blocks, end crystals
  'other'     an entity type number that is not in the game data; then entity.name is
              'unknown', entity.displayName is 'unknown', entity.kind is 'unknown' and
              entity.entityType is that number; height and width stay 0
  The values 'object', 'global', 'projectile' and 'hostile' of the type declaration are
  not produced on 1.16.1.

entity.name and entity.kind. Players and experience orbs have no kind (undefined);
their names are 'player' and 'experience_orb'.
  kind 'Hostile mobs'
    blaze, cave_spider, creeper, drowned, elder_guardian, ender_dragon, enderman,
    endermite, evoker, evoker_fangs, ghast, giant, guardian, husk, illusioner, magma_cube,
    phantom, pillager, ravager, shulker, silverfish, skeleton, slime, spider, stray, vex,
    vindicator, witch, wither, wither_skeleton, zombie, zombie_villager
  kind 'Passive mobs'
    bat, cat, chicken, cod, cow, dolphin, donkey, horse, iron_golem, llama, mule,
    mooshroom, ocelot, panda, parrot, pig, polar_bear, pufferfish, rabbit, salmon, sheep,
    skeleton_horse, snow_golem, squid, trader_llama, tropical_fish, turtle, villager,
    wandering_trader, wolf, zombie_horse
  kind 'UNKNOWN'
    bee, end_crystal, eye_of_ender, firework_rocket, fox, hoglin, lightning_bolt, piglin,
    strider, experience_bottle, trident, zoglin, zombified_piglin, fishing_bobber
  kind 'Projectiles'
    arrow, dragon_fireball, fireball, llama_spit, shulker_bullet, small_fireball,
    snowball, spectral_arrow, egg, ender_pearl, potion, wither_skull
  kind 'Vehicles'
    boat, minecart, chest_minecart, command_block_minecart, furnace_minecart,
    hopper_minecart, spawner_minecart, tnt_minecart
  kind 'Immobile'
    area_effect_cloud, armor_stand, item_frame, leash_knot
  kind 'Blocks'
    falling_block, tnt
  kind 'Drops'
    item

entity.displayName is the English name from the game data ('Zombie', 'Item', 'End
Crystal', 'Armor Stand'). entity.height and entity.width come from the same data, for
example zombie 1.95 and 0.6, item 0.25 and 0.25, boat 0.5625 and 1.375, end_crystal 2
and 2, armor_stand 1.975 and 0.5. A player is 1.8 high (1.5 crouching) and 0.6 wide. An
experience orb is 0.5 high and 0.5 wide.

Paintings are not in bot.entities: guide("entity-painting").
