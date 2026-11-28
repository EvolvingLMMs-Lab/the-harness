guide("run-channels"): the three channels (move, look, use): what each covers, how code says which it uses, what fails, which codes run at once.

The channels.
  The body has three channels. Each call that acts on the body uses one or two of them:
  move    the movement keys.
          bot.setControlState, bot.clearControlStates, bot.creative.flyTo
  look    the head.
          bot.look, bot.lookAt
  use     the hand: digging, placing, hitting, using an item, equipping, eating, the
          inventory and windows.
          bot.equip, unequip, consume, craft, toss, tossStack, fish, sleep, wake,
          clickWindow, transfer, moveSlotItem, putAway, putSelectedItemRange, trade, mount,
          dismount, elytraFly, attack, swingArm, activateItem, deactivateItem,
          setQuickBarSlot, closeWindow, stopDigging, updateHeldItem, openContainer,
          openChest, openFurnace, openDispenser, openEnchantmentTable, openAnvil,
          openVillager, openEntity; bot.creative.setInventorySlot, clearSlot,
          clearInventory, startFlying, stopFlying
  use and look (these turn the head to what they act on):
          bot.dig, placeBlock, placeEntity, activateBlock, activateEntity,
          activateEntityAt, openBlock
  No channel: bot.chat, bot.whisper, bot.waitForTicks, bot.waitForChunksToLoad, and
  every function that reads (blockAt, findBlocks, nearestEntity, getControlState, ...),
  every property, the listeners (bot.on, ...) and h.note. They work for any code.

How code says which channels it uses.
  The code of run_js and routine uses the channels its program unit claims: the unit
  started with spawn(fn, claims=[...]), the claims a unit adds with claim(...), a reflex
  set with set_reflex(..., claims=[...]). Of the claims only 'move', 'look' and 'use'
  count. None of them claimed: the code uses all three.
  Inside the code, h.channels is the list it uses (all three when none was said); the
  report of the run has it as `channels`.
  A routine called through `skills` runs on the channels of the run that called it.
  A sense uses no channel: it has the bot itself, with no gate (guide("run-senses")).

What fails.
  A call on a channel the code did not say it uses throws an Error:
    "<call> uses the channel <channels missing>: this code said it uses <its channels>"
  for example 'dig uses the channel look: this code said it uses use' and 'creative flyTo
  uses the channel move: this code said it uses look'. A call that returns a promise
  rejects with it; a call that happens at once throws it. Nothing is done on the body.
  A call on two channels needs both.
  Code that uses all three channels never gets this error.

Which codes run at once.
  Every running job uses its channels; two jobs share a channel when both use it (a job
  that said none uses all three, and shares with every job).
  - Starting a run ends every running job that shares a channel with it: each is told to
    stop with the cause 'another job' (its report: ended "other code took the body"), and
    the new run starts when they are over (guide("run-gate")). Running jobs on other
    channels go on. Paused jobs are not ended.
  - Jobs on channels of their own run at the same time, each with its own context,
    timers, listeners and `did` counters.
  - A unit of higher priority that takes channels pauses only the running jobs that share
    one of those channels with it (guide("run-pause")); the others go on.
  - A resumed job ends first every running job that shares a channel with it.
  The state lists every running job in jobs_running and every paused one in jobs_paused
  (guide("run-state")).

What is counted, by channel.
  What the body does is counted in the `did` of the running job that holds the channel
  it was done on (guide("run-report")): dug, placed and broke for the job on use; moved
  and pulled_back for the job on move. With no running job on that channel, nothing is
  counted.

What is let go, by channel.
  When a job is paused or ends, only its own channels are let go:
    move   bot.clearControlStates(): every key up
    use    bot.stopDigging() and bot.deactivateItem(): a dig stops, an item in use is no
           longer used
    look   nothing: the head stays where it is
  At a resume, the keys the job recorded as held are pressed again (move) and the item it
  held is put back in the hand (use) (guide("run-pause")).

The keys and the head.
  The movement keys move the body relative to the yaw of the head (guide("physics-keys"),
  guide("look")): forward is along (-sin(yaw), -cos(yaw)) in (x, z). When one job holds
  move and another holds look, a turn of the head made by the second changes the direction
  the first one's keys move the body, from the next physics tick. The job on move reads
  bot.entity.yaw and chooses its keys from it.
