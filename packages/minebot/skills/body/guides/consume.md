guide("consume"): bot.consume(): eating or drinking the item in the hand.

bot.consume() -> Promise
  Steps, in order:
  1. When an earlier bot.consume() is still running, that earlier promise is rejected
     with 'Consuming cancelled due to calling bot.consume() again'.
  2. When bot.game.gameMode is not 'creative', bot.food is exactly 20, and
     bot.heldItem.name is none of 'potion', 'milk_bucket', 'enchanted_golden_apple',
     'golden_apple': it throws 'Food is full'. Nothing is sent.
     With an empty hand in a mode other than creative this step throws a TypeError
     (bot.heldItem is null).
  3. It calls bot.activateItem(): bot.usingHeldItem becomes true and one use-item packet
     for the main hand is sent.
  4. It waits for the eating to end, 2500 ms at most.
  Resolves with nothing when one of these arrives during the wait:
  - an entity-status packet for the bot's own entity with status 9 (the server's "item
    use finished");
  - a 'heldItemChanged' event emitted while the hand holds an item. That event fires on
    every slot packet and every click answer (guide("hand-held-item")), so the promise
    also resolves when some other slot changes, before the food is eaten;
  - a set-cooldown packet when the hand is empty or its item id equals the held item's
    type.
  Rejects with 'Promise timed out.' when none arrives within 2500 ms. The use-item packet
  is already sent in that case, and bot.usingHeldItem stays true.
  It does not check that the held item is edible, and it does not send a release.

Measured in the game.
  Eating or drinking takes 1.6 seconds.
  With bot.food at 20 it rejects with 'Food is full', except for golden apples, potions
  and milk.
  For an item that cannot be eaten it rejects with 'Promise timed out.'.
  A change of the held item ends it.

Related state.
bot.food                             the food level, 0 to 20; step 2 tests it against 20
bot.usingHeldItem                    true while the item is in use; guide("hand-use-item")
bot.heldItem                         the item that is eaten; guide("hand-held-item")
