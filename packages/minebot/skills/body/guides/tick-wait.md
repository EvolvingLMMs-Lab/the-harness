guide("tick-wait"): bot.waitForTicks: waiting a number of physics ticks.

bot.waitForTicks(ticks) -> Promise
  ticks: number.
  1. ticks at or below 0: resolves at once.
  2. Starts a time limit of ticks * 50 + 5000 ms.
  3. Listens to 'physicsTick'. Each event takes 1 from the count. When the count is
     exactly 0 it resolves with undefined and removes the listener and the time limit.
  4. At the time limit it removes the listener and rejects with
     'Timeout waiting for <n> ticks after <n * 50 + 5000>ms', where n is the count still
     left at that moment (not the number passed in).

  It counts 'physicsTick' events and nothing else. guide("tick-loop") lists when that
  event is emitted. With none emitted (body mounted, dead, in a chunk that is not
  loaded, bot.physicsEnabled false, connection ended) the count stays and the call
  rejects at the time limit.
  A count that is not a whole number does not reach exactly 0: waitForTicks(2.5) rejects
  at its time limit.
  Ticks follow real time at 20 a second. After a pause of the process up to 4 ticks run
  in one 50 ms firing, so n ticks can pass in less than n * 50 ms.
