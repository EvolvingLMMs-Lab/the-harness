guide("run-bot"): the bot object code on the body is given; how its calls are gated.

What it is.
  `bot` is a Proxy of the one Mineflayer bot of the body's process. Each run has a proxy
  of its own; a routine called through `skills` gets the proxy of the run that called it.
  Reading a property whose value is not a function gives the bot's own value. bot.entity,
  bot.inventory, bot.registry, bot.world, bot.game, bot.simpleClick and bot._client are
  the bot's own objects: their methods run at once and are not gated.
  bot.creative is a second proxy: setInventorySlot, clearSlot, clearInventory and flyTo
  wait at the gate as the waiting calls do; startFlying and stopFlying are calls that
  happen at once.
  There is no bot.pathfinder: the body is walked by its navigator through h.go
  (guide("nav-go")), or by the keys (guide("control-keys")) and the head (guide("look"))
  that code sets itself.
  Writing a property (bot.x = 1) writes it on the Mineflayer bot itself. It stays for
  later runs until the body's process is started again.
  Reading a function gives, by its name, one of the three kinds below. The gate is the
  check each gated call makes: whether this run is running and not paused
  (guide("run-gate")).

Channels.
  Each call that acts uses one or two of the body's channels: move (the keys), look (the
  head), use (the hand) (guide("run-channels")). A call on a channel the code did not
  say it uses fails with the error '<call> uses the channel X: this code said it uses
  ...', and does nothing. Code that said no channels uses all three.

Calls that wait at the gate.
  bot.dig, placeBlock, placeEntity, equip, unequip, consume, craft, lookAt, look,
  activateBlock, activateEntity, activateEntityAt, openContainer, openChest, openFurnace,
  openDispenser, openEnchantmentTable, openAnvil, openVillager, openBlock, openEntity,
  toss, tossStack, fish, sleep, wake, clickWindow, transfer, moveSlotItem, putAway,
  putSelectedItemRange, trade, mount, elytraFly, waitForTicks, waitForChunksToLoad.
  Each returns a promise and does this:
  1. The call uses a channel the code did not say it uses: rejects with the channel
     error.
  2. The run has ended: rejects with 'this code has ended: it no longer has the body'.
     The run was told to stop: rejects with 'stopped'. The run is paused: waits until it
     is resumed (rejects with 'stopped' when it is told to stop while it waits).
  3. Calls the bot's own function with the same arguments.
  4. Settles with what that function returns or throws. When the run is told to stop
     before it settles, the promise rejects with 'stopped' at once.
  Of these, dig, lookAt, look, consume, fish and waitForTicks are done again after a
  pause: when the run is paused while one is under way, the promise stays pending, waits
  until the run is resumed, and goes back to step 3 with the same arguments. An error
  such a call throws after a pause began is not passed on; the call is made again. The
  others, once started, go on through a pause and settle with their own outcome.

Calls that happen at once.
  bot.setControlState, clearControlStates, attack, swingArm, activateItem, deactivateItem,
  setQuickBarSlot, chat, whisper, dismount, closeWindow, stopDigging, updateHeldItem.
  The run has ended: the call throws 'this code has ended: it no longer has the body'.
  The call uses a channel the code did not say it uses: it throws the channel error.
  The run is paused: the call does nothing and returns undefined.
  Otherwise the bot's own function is called and its value returned, also after the run
  was told to stop, until it ends.
  setControlState(key, value) and clearControlStates() are recorded for the run in every
  case, also while paused: a resume presses the keys recorded as true.

Listeners.
  bot.on, bot.once, bot.addListener, bot.prependListener, bot.prependOnceListener
  (event, fn) put fn on the Mineflayer bot, record the pair for the run, and return the
  proxy. The listener runs whenever the bot emits the event, paused or not, with `this`
  the Mineflayer bot itself. When the run ends, each recorded listener that is still on
  the bot is taken off. bot.off, bot.removeListener, bot.removeAllListeners and bot.emit
  are the bot's own. Listeners put on other objects (bot._client, bot.inventory, a window)
  are not recorded and stay after the run. Listeners use no channel.

Every other function.
  It is the bot's own function bound to the Mineflayer bot: it runs at once, whether the
  run is paused, told to stop or ended, and uses no channel. bot.blockAt, bot.findBlocks,
  bot.nearestEntity, bot.recipesFor, bot.getControlState, bot.useOn, bot.respawn,
  bot.setSettings and bot.awaitMessage are of this kind.
  What a call returns is the library's own object: the methods of a window or furnace a
  gated open call resolved with (deposit, withdraw, takeOutput, close) are not gated.
