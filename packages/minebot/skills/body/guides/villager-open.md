guide("villager-open"): bot.openVillager: the trading window and the list of trades.

bot.openVillager(villagerEntity) -> Promise<villager>
  1. villagerEntity.entityType is not the id of the entity type 'villager': rejects with
     an AssertionError. A wandering_trader has another type id and is rejected here.
     Nothing is sent.
  2. Calls bot.openEntity(villagerEntity): the bot turns its head to the entity's
     position plus 1 block up, sends one interact packet with the main hand, and waits
     for the bot event 'windowOpen', 20 seconds at most ('Event windowOpen did not fire
     within timeout of 20000ms'). The code checks no distance.
  3. The window's type is neither 'minecraft:villager' nor 'minecraft:merchant' (1.16.1
     gives 'minecraft:merchant'): rejects with 'Expected minecraft:villager or
     minecraft:mechant type, but got ' followed by the type; that window stays open.
  4. Sets villager.trades and villager.selectedTrade to null, adds villager.trade.
  5. Waits for the trade list of this window, 20 seconds at most ('Event ready did not
     fire within timeout of 20000ms'), then resolves with the window. villager.trades is
     filled when it resolves.

Slots of the window.
  0 first input, 1 second input, 2 output, 3 to 38 the bot's inventory (30 to 38 the
  hotbar).

villager.trades            array of trades, in the order the server sent them; the index
                           in this array is the trade's index for villager.trade
villager.selectedTrade     the trade last passed to villager.trade / bot.trade; null
                           before the first call
villager 'ready' event     no arguments; emitted once, when the first trade list for
                           this window has been stored

A trade.
  inputItem1            Item: the first item the villager takes; count is the base price
  inputItem2            Item: the second item the villager takes; undefined when the
                        trade has one input
  hasItem2              true when inputItem2 exists and has a type and a count
  outputItem            Item: what the villager gives
  inputs                [inputItem1] or [inputItem1, inputItem2]
  outputs               [outputItem]
  tradeDisabled         boolean, as the server sent it; bot.trade sets it true when
                        nbTradeUses reaches maximumNbTradeUses
  nbTradeUses           how many times the trade has been used; bot.trade adds 1 for
                        each trade it makes
  maximumNbTradeUses    uses after which the trade is out of stock
  xp, specialPrice, priceMultiplier, demand    numbers, as the server sent them
  realPrice             the number of inputItem1 one trade costs now:
                        inputItem1.count + specialPrice
                        + max(0, floor(inputItem1.count * demand * priceMultiplier)),
                        kept between 1 and inputItem1.stackSize

Updates.
  Each later trade list packet for this window replaces villager.trades with a new array
  of new trade objects (the server's nbTradeUses and prices at that moment). No event is
  emitted for it. The listener is removed when the window emits 'close'; villager.close()
  emits it.
  The villager's level, its experience and whether it restocks are in the packet; the
  code does not store them.

Trading: guide("villager-trade"). villager.close(): guide("window-open-close").
villager.items(), count(): guide("window-object").
