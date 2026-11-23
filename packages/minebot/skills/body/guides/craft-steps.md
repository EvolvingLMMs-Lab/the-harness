guide("craft-steps"): the clicks of one application of a recipe in bot.craft.

Slots.
  The grid is w by h: 2 by 2 in the inventory window, 3 by 3 in a table window. The cell
  in column x, row y (from 0, top left) is slot 1 + x + w * y. Slot 0 is the result.
  The inventory part of the window is slots 9 to 44 (inventory window) or 10 to 45 (table
  window); the last 9 of them are the hotbar.
  The cursor is window.selectedItem: the stack picked up by a click.

1. Placing a shaped recipe (recipe.inShape).
  The cells are visited row by row, left to right. An empty cell (id -1) is skipped.
  For each other cell:
    - When the cursor is empty or holds another item id: the code takes the lowest
      numbered slot of the inventory part that holds the ingredient's id. None: 'missing
      ingredient'. It left-clicks that slot: the whole stack goes on the cursor, and a
      stack that was on the cursor goes into that slot.
    - It right-clicks the cell's slot: one item of the cursor goes into the cell.
  The shape sits in the top left corner of the grid.

2. Placing a shapeless recipe (recipe.ingredients).
  The entries are visited in order. Each goes into a free grid slot, the highest numbered
  first (inventory grid: 4, 3, 2, 1; table grid: 9 down to 1). The cursor is filled and
  the item placed with the same two clicks as in 1.

3. Putting the rest of the cursor back.
  While the cursor holds a stack:
    - a stack of the same item in the inventory part that is not full: left-click it;
    - else the first empty slot of the inventory part: left-click it;
    - else: left-click the slot the first ingredient was taken from, then, when the
      cursor still holds items, left-click outside the window (slot -999): the stack is
      thrown on the ground.

4. Taking the result.
  The code asserts that the cursor is empty. It writes the result item (recipe.result.id,
  recipe.result.count) into slot 0 of its own copy of the window, without waiting for the
  server to send it. Then bot.putAway(0): a left-click on slot 0 takes the result on the
  cursor, and the cursor is put into the inventory part: on a stack of the same item that
  is not full, else on the first empty slot; with neither it is thrown on the ground. The
  code waits for slot 0 to change, 20 seconds at most.
  The click on slot 0 carries the item the bot's copy holds in that slot; when the server
  refuses the click the call ends with 'Server rejected transaction for clicking on slot
  0, on window with id W.'.

5. Clearing the grid.
  recipe.outShape null: the code sets grid slots 1 to w * h to empty in its own copy of
  the window. It sends nothing.
  recipe.outShape present (cake): the code writes each outShape item into its grid slot in
  its own copy, then calls bot.putAway on each such slot: a shift-click when the
  inventory part has a stack to join or an empty slot, else a left-click and the cursor is
  thrown on the ground.

With count above 1, steps 1 to 5 run again from the start for each application. The
ingredients are looked up again each time, so a later application takes them from
another slot once the first one is empty.
