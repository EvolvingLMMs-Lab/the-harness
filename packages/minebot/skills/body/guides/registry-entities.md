guide("registry-entities"): the entity records of bot.registry, field by field.

bot.registry.entities[id], bot.registry.entitiesByName[name], bot.registry.entitiesArray
  107 records on 1.16.1, ids 0 to 106.
  { id: 101, internalId: 101, name: 'zombie', displayName: 'Zombie', width: 0.6,
    height: 1.95, type: 'mob', category: 'Hostile mobs' }

Fields.
id             number, the entity type id the server sends when it spawns the entity
internalId     number, equal to id in every record
name           string, for example 'ender_dragon' (Entity.name)
displayName    string, for example 'Ender Dragon'
width          number, the width of the entity in blocks (zombie 0.6, item 0.25,
               ender_dragon 16)
height         number, the height in blocks (zombie 1.95, item 0.25, ender_dragon 8)
type           'mob' on 101 records, 'UNKNOWN' on 6 (bee, hoglin, piglin, strider,
               zoglin, zombified_piglin). Dropped items, arrows, boats, minecarts and
               the player record are 'mob' too
category       one of:
  'Hostile mobs' (32)  blaze, cave_spider, creeper, drowned, elder_guardian,
               ender_dragon, enderman, endermite, evoker, evoker_fangs, ghast, giant,
               guardian, husk, illusioner, magma_cube, phantom, pillager, ravager,
               shulker, silverfish, skeleton, slime, spider, stray, vex, vindicator,
               witch, wither, wither_skeleton, zombie, zombie_villager
  'Passive mobs' (31)  bat, cat, chicken, cod, cow, dolphin, donkey, horse, iron_golem,
               llama, mule, mooshroom, ocelot, panda, parrot, pig, polar_bear,
               pufferfish, rabbit, salmon, sheep, skeleton_horse, snow_golem, squid,
               trader_llama, tropical_fish, turtle, villager, wandering_trader, wolf,
               zombie_horse
  'Projectiles' (12)   arrow, dragon_fireball, fireball, llama_spit, shulker_bullet,
               small_fireball, snowball, spectral_arrow, egg, ender_pearl, potion,
               wither_skull
  'Vehicles' (8)       boat, minecart, chest_minecart, command_block_minecart,
               furnace_minecart, hopper_minecart, spawner_minecart, tnt_minecart
  'Immobile' (5)       area_effect_cloud, armor_stand, item_frame, leash_knot, painting
  'Blocks' (2)         falling_block, tnt
  'Drops' (1)          item
  'UNKNOWN' (16)       bee, end_crystal, experience_orb, eye_of_ender, firework_rocket,
               fox, hoglin, lightning_bolt, piglin, strider, experience_bottle, trident,
               zoglin, zombified_piglin, player, fishing_bobber

bot.registry.mobs[id]        the 101 records whose type is 'mob', keyed by id
bot.registry.objects         {} on 1.16.1: no record has type 'object'

What a killed entity drops: bot.registry.entityLoot, guide("registry-loot").
