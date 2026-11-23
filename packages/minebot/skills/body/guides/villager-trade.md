guide("villager-trade"): bot.trade and villager.trade: how one trade is carried out.

bot.trade(villager, index, count) -> Promise<void>
villager.trade(index, count) -> Promise<void>      the same, for that villager window
  villager: the open window from bot.openVillager; see guide("villager-open").
  index: the index in villager.trades; a string is parsed.
  count: how many times to make the trade. 0, null or undefined: every use left
    (maximumNbTradeUses - nbTradeUses).
  T below is villager.trades[index]; left is T.maximumNbTradeUses - T.nbTradeUses.

Checks, in this order. Nothing is sent before they pass.
  villager.trades is null: AssertionError.
  No trade at that index: TypeError.
  villager.selectedTrade is set to T.
  left is 0 or less: AssertionError 'trade blocked'.
  count is above left: AssertionError.
  villager.count(T.inputItem1.type, T.inputItem1.metadata) is below T.realPrice * count:
    rejects with 'Not enough item 1 to trade'.
  T.hasItem2 and villager.count(T.inputItem2.type, ...) is below T.inputItem2.count *
    count: rejects with 'Not enough item 2 to trade'.
  villager.count adds up the inventory part of the window (slots 3 to 38); items already
  in slots 0 and 1 are not counted. T.tradeDisabled is not read.

Steps.
  1. Sends the select-trade packet with index.
  2. Waits for the server to write slot 0 of the window, and slot 1 when T.hasItem2,
     20 seconds at most each ('Event updateSlot:0 did not fire within timeout of
     20000ms').
  3. count times:
     a. Slot 0 holds fewer than T.realPrice items: moves the missing number of
        inputItem1 from slots 3 to 38 into slot 0 with bot.transfer. The same for slot 1
        with T.inputItem2.count when T.hasItem2.
     b. T.nbTradeUses += 1; when it reaches T.maximumNbTradeUses, T.tradeDisabled = true.
     c. In its own copy of the window the code writes a copy of T.outputItem into slot 2,
        takes T.realPrice off slot 0 and T.inputItem2.count off slot 1 (a slot at 0 or
        less becomes empty). Slot 0 holding another item type than inputItem1, or slot 1
        another than inputItem2: AssertionError.
     d. bot.putAway(2): left-clicks slot 2 (the output goes on the cursor) and puts the
        cursor into the inventory part: on a stack of the same item that is not full,
        else on the first empty slot, else it is thrown on the ground. Waits for slot 2
        to change, 20 seconds at most.
  4. For slot 0, then slot 1: when it still holds items, bot.putAway on it: one
     shift-click when the inventory part has a stack to join or an empty slot; else a
     left-click, and the cursor is thrown on the ground.
  5. Resolves with undefined. The window stays open.

Other rejections.
  "Can't find NAME in slots [3 - 39], (item id: ID)", 'destination full': from
    bot.transfer in step 3a.
  'Event updateSlot:N did not fire within timeout of 20000ms': steps 2, 3d, 4.
  "Server didn't respond to transaction for clicking on slot S on window with id W.":
    one click got no answer within 5 seconds.
  'Server rejected transaction for clicking on slot S, on window with id W.'
  A rejection in step 3 leaves the trades already made in place; T.nbTradeUses keeps the
  number of step 3b.
