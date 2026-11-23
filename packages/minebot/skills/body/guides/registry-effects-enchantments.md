guide("registry-effects-enchantments"): the effect and enchantment records of bot.registry.

bot.registry.effects[id], bot.registry.effectsByName[name], bot.registry.effectsArray
  32 records on 1.16.1, ids 1 to 32.
  { id: 3, name: 'Haste', displayName: 'Haste', type: 'good' }
  id            number, the key of bot.entity.effects and the id in entity effect events
  name          capitalised, no spaces: the key of effectsByName
  displayName   string
  type          'good' or 'bad'
  All effects, id name (bad ones marked -):
    1 Speed, 2 Slowness -, 3 Haste, 4 MiningFatigue -, 5 Strength, 6 InstantHealth,
    7 InstantDamage -, 8 JumpBoost, 9 Nausea -, 10 Regeneration, 11 Resistance,
    12 FireResistance, 13 WaterBreathing, 14 Invisibility, 15 Blindness -,
    16 NightVision, 17 Hunger -, 18 Weakness -, 19 Poison -, 20 Wither -,
    21 HealthBoost, 22 Absorption, 23 Saturation, 24 Glowing -, 25 Levitation -,
    26 Luck, 27 BadLuck -, 28 SlowFalling, 29 ConduitPower, 30 DolphinsGrace,
    31 BadOmen, 32 HeroOfTheVillage

bot.registry.enchantments[id], bot.registry.enchantmentsByName[name],
bot.registry.enchantmentsArray
  34 records, ids 0 to 33.
  { id: 11, name: 'sharpness', displayName: 'Sharpness', maxLevel: 5,
    minCost: { a: 11, b: -10 }, maxCost: { a: 11, b: 10 },
    exclude: ['smite', 'bane_of_arthropods'], category: 'weapon', weight: 10,
    treasureOnly: false, curse: false, tradeable: true, discoverable: true }
  id            number
  name          string, the name in an item's enchantment list (item.enchants)
  displayName   string
  maxLevel      the highest level
  minCost, maxCost   { a, b }: the cost at a level is a * level + b
  exclude       names of enchantments that cannot be on the same item
  category      which items take it: one of the enchantCategories strings of the item
                records ('weapon', 'digger', 'armor', 'armor_head', 'armor_chest',
                'armor_feet', 'wearable', 'bow', 'fishing_rod', 'trident', 'breakable',
                'vanishable')
  weight        the rarity weight: 10, 5, 2 or 1
  treasureOnly  true for frost_walker, binding_curse, mending, vanishing_curse
  curse         true for binding_curse, vanishing_curse
  tradeable, discoverable   true on every record
  All enchantments, id name maxLevel category:
    0 protection 4 armor, 1 fire_protection 4 armor, 2 feather_falling 4 armor_feet,
    3 blast_protection 4 armor, 4 projectile_protection 4 armor,
    5 respiration 3 armor_head, 6 aqua_affinity 1 armor_head, 7 thorns 3 armor_chest,
    8 depth_strider 3 armor_feet, 9 frost_walker 2 armor_feet,
    10 binding_curse 1 wearable, 11 sharpness 5 weapon, 12 smite 5 weapon,
    13 bane_of_arthropods 5 weapon, 14 knockback 2 weapon, 15 fire_aspect 2 weapon,
    16 looting 3 weapon, 17 sweeping 3 weapon, 18 efficiency 5 digger,
    19 silk_touch 1 digger, 20 unbreaking 3 breakable, 21 fortune 3 digger,
    22 power 5 bow, 23 punch 2 bow, 24 flame 1 bow, 25 infinity 1 bow,
    26 luck_of_the_sea 3 fishing_rod, 27 lure 3 fishing_rod, 28 loyalty 3 trident,
    29 impaling 5 trident, 30 riptide 3 trident, 31 channeling 1 trident,
    32 mending 1 breakable, 33 vanishing_curse 1 vanishable
  The table has no record for multishot, piercing, quick_charge or soul_speed.
