guide("recipe-object"): the Recipe object and its RecipeItem entries, field by field.

A Recipe is what bot.recipesFor, bot.recipesAll and Recipe.find return and what bot.craft
takes. It is a plain object with data fields; it has no methods. Writing a field changes
that one object only.

RecipeItem { id, metadata, count }
  id        numeric item id. -1: an empty cell of a shape.
  metadata  null in every recipe of 1.16.1.
  count     a number of items; its meaning depends on the field it sits in (below).

recipe.result            RecipeItem
  The item made. count: how many items one application of the recipe makes (sticks: 4).

recipe.inShape           [[RecipeItem]] or null
  The shaped layout: an array of rows, each row an array of cells, row 0 first. Every cell
  has count 1; an empty cell has id -1. null for a shapeless recipe.
  bot.craft puts row 0 in the top row of the grid and cell 0 of each row in the left
  column.

recipe.ingredients       [RecipeItem] or null
  The items of a shapeless recipe, one entry for each item used, each with count -1.
  null for a shaped recipe. No recipe of 1.16.1 has both inShape and ingredients.

recipe.outShape          [[RecipeItem]] or null
  What stays in the grid after the result is taken, in the layout of inShape. null for
  every recipe of 1.16.1 except cake: its row 0 is three buckets, the other cells are
  empty (id -1).

recipe.delta             [RecipeItem]
  The change of the inventory after one application: one entry for each item id, count
  negative for what is used up, positive for what is gained. The last entry is the result
  with +result.count.
  Sticks from oak planks: [{ oak_planks, -2 }, { stick, +4 }].
  A wooden pickaxe: [{ oak_planks, -3 }, { stick, -2 }, { wooden_pickaxe, +1 }].
  For cake the computed delta is [{ milk_bucket, 0 }, { sugar, 0 }, { egg, 0 },
  { wheat, 0 }, { cake, +1 }]: no entry is negative and bucket is absent, so the
  inventory check of bot.recipesFor passes for cake whatever the inventory holds.

recipe.requiresTable     boolean
  true when the recipe does not fit the 2 by 2 grid of the inventory:
    inShape has more than 2 rows, or one of its rows has more than 2 cells; or
    the cells of inShape (empty cells included) plus the entries of ingredients number
    more than 4.
  931 of the 1197 recipes of 1.16.1 have requiresTable true.

How a Recipe is built from the data.
  new Recipe(raw) reads one raw recipe of bot.registry.recipes: a raw cell or ingredient
  is an item id or null; result is { id, count }. Each becomes a RecipeItem: a number
  gives { id, metadata: null, count: 1 }, null gives { id: -1, metadata: null, count: 1 },
  an object gives { id, metadata or null, count or 1 }. The count of each ingredients
  entry is then set to -1. delta and requiresTable are computed once, when the object is
  built.

RecipeItem.fromEnum(raw) -> RecipeItem        the conversion above
RecipeItem.clone(recipeItem) -> RecipeItem    a new RecipeItem with the same three fields
  RecipeItem is require('prismarine-recipe')(bot.registry).RecipeItem.
  new RecipeItem(id, metadata, count) builds one from the three values.
