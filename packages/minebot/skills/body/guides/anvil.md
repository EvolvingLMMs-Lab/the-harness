guide("anvil"): bot.openAnvil and the anvil window: combine and rename.

bot.openAnvil(anvilBlock) -> Promise<anvil>
  Calls bot.openBlock(anvilBlock): the bot turns its head to the centre of the block,
  sends one use-block packet on its top face, and waits for the bot event 'windowOpen',
  20 seconds at most ('Event windowOpen did not fire within timeout of 20000ms'). No
  distance check, no check of the block.
  The window's type has to contain 'minecraft:anvil', 'minecraft:chipped_anvil' or
  'minecraft:damaged_anvil'; else it rejects with 'Not a anvil-like window: ' followed by
  the window as JSON, and that window stays open.
  Resolves with the window, with combine and rename added.
  Slots: 0 first item, 1 second item, 2 result, 3 to 38 the bot's inventory.

anvil.combine(itemOne, itemTwo, name) -> Promise<void>
  itemOne, itemTwo: Item objects that are in the bot's inventory. name: optional string,
  the new name of the result.
  1. name longer than 35 characters: closes the window, rejects with 'Name is too long.'
  2. itemOne or itemTwo falsy: AssertionError.
  3. Computes normalCost = Item.anvil(itemOne, itemTwo, creative, name).xpCost and
     inverseCost = Item.anvil(itemTwo, itemOne, creative, name).xpCost; creative is
     bot.game.gameMode === 'creative'. The cost rules: guide("anvil-cost").
     Both 0: closes the window, rejects with
     'Not anvil-able (in either direction), cancelling.'
  4. Level check, outside creative: only when normalCost is 0, it compares
     bot.experience.level with inverseCost; a lower level closes the window and rejects
     with 'Player does not have enough xp to do action, cancelling.' When normalCost is
     above 0 the code makes no level check.
  5. Outside creative it starts waiting for the bot event 'experience', 20 seconds at
     most from this point.
  6. Order of the two items: normalCost 0: itemTwo in slot 0, itemOne in slot 1.
     inverseCost 0: itemOne in slot 0, itemTwo in slot 1. Both above 0: the cheaper order;
     normalCost lower: itemOne in slot 0; equal or higher: itemTwo in slot 0.
  7. Moves the first item (its id, metadata, count, nbt) from slots 3 to 38 to slot 0
     with bot.transfer, sends two name packets with an empty name, moves the second item
     to slot 1.
  8. With a name: sends one name packet for each prefix of the name (1 character, 2,
     ... the whole name), 50 ms after each.
  9. bot.putAway(2): left-clicks the result slot and puts the cursor into the inventory
     part (a stack with room, else an empty slot, else thrown on the ground); waits for
     slot 2 to change, 20 seconds at most.
  10. Waits for the 'experience' event of step 5. Resolves with undefined. The window
     stays open.

anvil.rename(item, name) -> Promise<void>
  1. name longer than 35 characters: closes the window, 'Name is too long.'
  2. item falsy: AssertionError.
  3. cost = Item.anvil(item, null, creative, name).xpCost. 0: closes the window, rejects
     with 'Not valid rename, cancelling.' (one case: the item already has that name).
  4. Outside creative, bot.experience.level below cost: closes the window, rejects with
     'Player does not have enough xp to do action, cancelling.'
  5. Starts waiting for the bot event 'experience', 20 seconds at most, in creative too.
  6. Moves the item to slot 0, sends two name packets with an empty name, then the
     prefixes of the name, 50 ms after each, then bot.putAway(2) as above, then waits
     for the 'experience' event.

Other rejections of both.
  'Event experience did not fire within timeout of 20000ms'
  'Event updateSlot:2 did not fire within timeout of 20000ms'
  "Can't find NAME in slots [3 - 39], (item id: ID)", 'destination full' (slot 0 or 1
  already holds another item): from bot.transfer.
  "Server didn't respond to transaction for clicking on slot S on window with id W."
  (5 seconds), 'Server rejected transaction for clicking on slot S, on window with id W.'
  After these the window stays open.

anvil.deposit, withdraw, close(): guide("window-open-close").
anvil.items(): guide("window-object").
