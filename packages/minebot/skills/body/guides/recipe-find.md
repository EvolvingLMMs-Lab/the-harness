guide("recipe-find"): finding crafting recipes: bot.recipesFor, bot.recipesAll, Recipe.find.

bot.recipesFor(itemType, metadata, minResultCount = 1, craftingTable) -> [Recipe]
  Returns the recipes that make itemType and that the inventory covers now.
  itemType: the numeric id of the item to make (bot.registry.itemsByName.NAME.id). A name,
    or an id that has no recipe, gives [].
  metadata: has no effect on 1.16.1; every value gives the same list.
  minResultCount: how many items of the result are wanted. null or undefined: 1.
  craftingTable: read only as true or false (a crafting table Block, or null). The code
    does not look at what block it is or how far it is.
  For each recipe of Recipe.find(itemType, metadata), in the order of the data:
    1. A recipe with requiresTable true is left out when craftingTable is falsy.
    2. craftCount = ceil(minResultCount / recipe.result.count).
    3. For every entry d of recipe.delta:
       bot.inventory.count(d.id, d.metadata) + d.count * craftCount is 0 or more.
       A recipe that fails this for one entry is left out.
  bot.inventory.count adds up slots 9 to 44 of bot.inventory (the 27 inventory slots and
  the 9 hotbar slots). The armour slots, the 2 by 2 grid, the off hand and the item on the
  cursor are not counted.
  Each ingredient id is counted on its own. Each kind of wood has its own recipe: planks of
  two woods do not add up in one.
  While a window is open (a furnace, a chest, a crafting table), bot.inventory is not kept
  up to date.
  The cake recipe passes step 3 whatever the inventory holds; see guide("recipe-object").
  Each call builds new Recipe objects. It sends nothing and waits for nothing.

bot.recipesAll(itemType, metadata, craftingTable) -> [Recipe]
  Returns every recipe of Recipe.find(itemType, metadata), whatever the inventory holds.
  A recipe with requiresTable true is left out when craftingTable is falsy. metadata has
  no effect on 1.16.1.

Recipe.find(itemType, metadata) -> [Recipe]
  Recipe is require('prismarine-recipe')(bot.registry).Recipe.
  Reads bot.registry.recipes[itemType], the list of raw recipes whose result is that item
  id, and returns one new Recipe object for each, in the same order. No such key: [].
  metadata has no effect on 1.16.1: no raw recipe of 1.16.1 has the field the code tests.

The recipe data of 1.16.1.
  bot.registry.recipes is an object keyed by the result item id. 562 items have recipes;
  there are 1197 recipes in all: 1029 shaped (inShape), 168 shapeless (ingredients).
  A raw shaped recipe: { inShape: [[id or null, ...], ...], result: { id, count } }.
  A raw shapeless recipe: { ingredients: [id, ...], result: { id, count } }.
  One raw recipe has outShape as well: cake.
  Every entry is a recipe of the crafting grid. The data has one recipe for each exact
  set of ingredient ids: sticks have 9 recipes (8 kinds of planks, and bamboo), oak planks
  have 4 (oak_log, oak_wood, stripped_oak_log, stripped_oak_wood).
