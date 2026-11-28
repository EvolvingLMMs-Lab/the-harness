guide("craft"): bot.craft: what it checks, when it ends, every error.

bot.craft(recipe, count = 1, craftingTable) -> Promise<void>
  Applies recipe count times by clicking slots of a crafting window. One application
  makes recipe.result.count items: count 2 of the stick recipe makes 8 sticks.
  recipe: a Recipe (bot.recipesFor, bot.recipesAll). See guide("recipe-object").
  count: null or undefined is 1; a string is parsed as a base 10 integer. 0 applies the
    recipe zero times and resolves.
  craftingTable: a crafting table Block, or null or undefined.

Which grid it uses.
  craftingTable falsy: the 2 by 2 grid of the inventory window (bot.inventory, slots 1 to
    4, result slot 0). Nothing is opened. While another window is open
    (bot.currentWindow), the clicks go to that window's slots instead.
  craftingTable truthy: the 3 by 3 grid of the table window (slots 1 to 9, result slot 0,
    inventory slots 10 to 45), also for a recipe with requiresTable false.

Steps.
  1. recipe falsy: rejects with an AssertionError.
  2. recipe.requiresTable true and craftingTable falsy: rejects with
     'Recipe requires craftingTable, but one was not supplied: ' followed by the recipe as
     JSON. Nothing has been clicked.
  3. With a table, before the first application: calls bot.activateBlock(craftingTable)
     (the bot turns its head to the centre of the block and sends one use-block packet on
     the block's top face) and waits for the bot event 'windowOpen', 20 seconds at most.
     The code checks no distance to the table and does not check the block's type before
     clicking it.
  4. The window that opened has a type that does not start with 'minecraft:crafting':
     error 'crafting: non craftingTable used as craftingTable: ' followed by the type.
  5. Applies the recipe count times, one after the other, in the same window. The clicks
     of one application are in guide("craft-steps").
  6. With a table, after the last application: bot.closeWindow(tableWindow). It sends the
     close packet, copies the inventory part of the table window into bot.inventory, sets
     bot.currentWindow to null, emits 'windowClose', then sends one click outside the
     inventory window and waits for its answer, 5 seconds at most; a failure of that
     click is ignored.
  7. Resolves with undefined.

Errors.
  Every error from step 3 on is caught, the table window (when one is open) is closed
  without waiting, and a new Error is thrown whose message is the text of the caught
  error with its name in front:
    'Error: missing ingredient'
      No slot of the inventory part of the window holds an item of an ingredient's id at
      the moment it is needed. Items already put in the grid are not taken back by the
      code, and a stack on the cursor stays on the cursor.
    'Error: Event windowOpen did not fire within timeout of 20000ms'
      No window opened within 20 seconds of step 3.
    'Error: crafting: non craftingTable used as craftingTable: TYPE'
    "Error: Server didn't respond to transaction for clicking on slot S on window with id
      W."  The server did not answer one click within 5 seconds.
    'Error: Server rejected transaction for clicking on slot S, on window with id W.'
      The server refused one click.
    'Error: Event updateSlot:0 did not fire within timeout of 20000ms'
      The result slot did not change within 20 seconds of the click that takes the result.
    'AssertionError [ERR_ASSERTION]: ...'
      The cursor still held an item when the result was about to be taken.
  An error in application k leaves the results of applications 1 to k-1 in the inventory.

Time.
  Each click waits for the server's confirmation of that click, 5 seconds at most. The
  code adds no other delay between clicks.
