guide("registry-items-and-foods"): the item and food records of bot.registry.

bot.registry.items[id], bot.registry.itemsByName[name], bot.registry.itemsArray
  974 records on 1.16.1, ids 1 to 974. There is no record for air or for id 0.
  Records:
    { id: 1, name: 'stone', displayName: 'Stone', stackSize: 64 }
    { id: 597, name: 'diamond_pickaxe', displayName: 'Diamond Pickaxe', stackSize: 1,
      maxDurability: 1561, enchantCategories: ['digger', 'breakable', 'vanishable'],
      repairWith: ['diamond'] }

Item fields.
id                 number, the item type id (Item.type, and the id the inventory calls take)
name               string, for example 'iron_ingot'
displayName        string, for example 'Iron Ingot'
stackSize          64, 16 or 1. 16: signs, banners, bucket, snowball, egg, ender_pearl,
                   written_book, armor_stand, honey_bottle. 1: 153 items (tools, armour,
                   filled buckets, beds, boats, potions, ...)
maxDurability      number of uses, on 65 items; absent on the rest
                     tools and swords: wooden 59, stone 131, iron 250, golden 32,
                     diamond 1561, netherite 2031
                     helmet / chestplate / leggings / boots: leather 55 80 75 65,
                     chainmail and iron 165 240 225 195, golden 77 112 105 91,
                     diamond 363 528 495 429, netherite 407 592 555 481
                     turtle_helmet 275, bow 384, crossbow 326, trident 250, shield 336,
                     elytra 432, shears 238, flint_and_steel 64, fishing_rod 64,
                     carrot_on_a_stick 25, warped_fungus_on_a_stick 100
enchantCategories  array of strings, on 70 items; absent on the rest. Values: 'weapon'
                   (swords), 'digger' (pickaxes, axes, shovels, hoes), 'armor',
                   'armor_head', 'armor_chest', 'armor_feet', 'wearable', 'bow',
                   'crossbow', 'fishing_rod', 'trident', 'breakable', 'vanishable'.
                   An enchantment record's category field holds one of these strings
repairWith         array of item names, on 57 items: what an anvil accepts to repair it
                   (iron_sword: ['iron_ingot']; elytra: ['phantom_membrane']; shield:
                   the eight planks). Absent on bow, crossbow, trident, shears,
                   fishing_rod, flint_and_steel and the two sticks

bot.registry.foods[id], bot.registry.foodsByName[name], bot.registry.foodsArray
  40 records, keyed by the item id and the item name of the food.
  { id: 621, name: 'bread', displayName: 'Bread', stackSize: 64, foodPoints: 5,
    saturation: 6, effectiveQuality: 11, saturationRatio: 1.2 }

Food fields.
id, name, displayName, stackSize    those of the item
foodPoints         what one item adds to the food level (bot.food)
saturation         what one item adds to the saturation
effectiveQuality   foodPoints + saturation
saturationRatio    saturation / foodPoints

All foods, as name foodPoints saturation:
  apple 4 2.4, baked_potato 5 6, beef 3 1.8, beetroot 1 1.2, beetroot_soup 6 7.2,
  bread 5 6, cake 2 0.4, carrot 3 3.6, chicken 2 1.2, chorus_fruit 4 2.4, cod 2 0.4,
  cooked_beef 8 12.8, cooked_chicken 6 7.2, cooked_cod 5 6, cooked_mutton 6 9.6,
  cooked_porkchop 8 12.8, cooked_rabbit 5 6, cooked_salmon 6 9.6, cookie 2 0.4,
  dried_kelp 1 0.6, enchanted_golden_apple 4 9.6, golden_apple 4 9.6,
  golden_carrot 6 14.4, honey_bottle 6 1.2, melon_slice 2 1.2, mushroom_stew 6 7.2,
  mutton 2 1.2, poisonous_potato 2 1.2, porkchop 3 1.8, potato 1 0.6, pufferfish 1 0.2,
  pumpkin_pie 8 4.8, rabbit 3 1.8, rabbit_stew 10 12, rotten_flesh 4 0.8, salmon 2 0.4,
  spider_eye 2 3.2, suspicious_stew 6 7.2, sweet_berries 2 0.4, tropical_fish 1 0.2
