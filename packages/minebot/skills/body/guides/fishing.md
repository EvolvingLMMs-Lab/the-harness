guide("fishing"): bot.fish: the steps, what it waits for, how it ends.

bot.fish() -> Promise
  1. A bot.fish still pending from an earlier call rejects with
     'Fishing cancelled due to calling bot.fish() again'.
  2. Calls bot.activateItem() once: a right click with the item in the hand. The call
     does not test what the hand holds.
  3. Takes as its bobber the first fishing_bobber entity that the server spawns after the
     call. It does not test whose bobber it is.
  4. Waits for a particle packet with: the 'fishing' particle, a count of exactly 6, and
     a position at most 1.23 blocks from the bobber measured in x and z. At that packet
     it calls bot.activateItem() again (reels in) and resolves with undefined.
  5. When the server removes the bobber entity before that, it rejects with
     'Fishing cancelled'.

  It has no time limit: it stays pending until step 4 or step 5 happens. With no bobber
  entity spawned after the call, neither happens.
  It resolves with no value: what was caught is not part of the result.
