guide("registry-recipes"): bot.registry.recipes, the raw crafting recipe table.

bot.registry.recipes[itemId] -> [recipe]
  Keyed by the numeric id of the item made. The value is an array of every recipe that
  makes that item. 562 item ids have recipes on 1.16.1, 1197 recipes in all; an id with
  no crafting recipe gives undefined (412 items).
  The table holds crafting-grid recipes. Items made only in a furnace, a smithing table
  or a brewing stand have no entry: recipes of stone, glass, netherite_sword and potion
  are undefined.

A shaped recipe.
  { inShape: [[581, 581, 581], [null, 599, null], [null, 599, null]],
    result: { id: 597, count: 1 } }
  inShape   array of rows, top row first; each row an array of item ids, left cell
            first; null is an empty cell. All rows have the same length. Rows and
            columns that are wholly empty are left out, so a shape is 1 to 3 wide and
            1 to 3 high: torch is [[579], [599]], bread is [[620, 620, 620]].
  result    { id, count }: the item made and how many one crafting gives.
  outShape  present on one recipe, cake: [[660, 660, 660], [null, null, null],
            [null, null, null]], what stays in the grid (three buckets).

A shapeless recipe.
  { ingredients: [582, 646], result: { id: 575, count: 1 } }      flint_and_steel
  ingredients   array of item ids, one entry for each item used; an id listed twice is
                used twice.
  result        as above.

Every ingredient on 1.16.1 is a plain item id (a number) or null. No recipe has both
inShape and ingredients: 1029 have inShape, 168 have ingredients.

One recipe for each ingredient variant.
  An item that can be made from several kinds of an ingredient has one recipe for each
  kind. stick (599) has 9: [[15], [15]] to [[22], [22]] for the eight planks (count 4)
  and [[135], [135]] for bamboo (count 1). crafting_table (183) has 8, one for each
  plank. Each of these recipes holds one kind of plank in all its cells.

More than one way.
  iron_ingot (582) has two: { ingredients: [137], count 9 } from an iron block and a
  3 by 3 inShape of item 905 (iron_nugget), count 1.

The Recipe objects that bot.recipesFor, bot.recipesAll and bot.craft work with are built
from these records.
