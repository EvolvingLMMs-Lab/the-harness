guide("run-differences"): what this bot has and does that a plain Mineflayer bot does not.

How the bot is made.
  mineflayer.createBot with: version '1.16.1', auth 'offline', respawn false (no
  automatic respawn: guide("run-death")), checkTimeoutInterval 120000 (the connection
  counts as lost after 120 seconds without a keep-alive from the game; the library's
  default is 30 seconds). Every other option has the library's default.
  No plugin is loaded beyond Mineflayer's own: there is no bot.pathfinder. The body has a
  navigator of its own, reached through h.go and h.path (guide("nav-go")); code can also
  set the keys and the head itself (guide("control-keys"), guide("look")).

Channels.
  The body has three channels, move (the keys), look (the head) and use (the hand), and
  each code acts only on the channels it says it uses; codes on channels of their own run
  at the same time (guide("run-channels")).

Every emitter in the process.
  EventEmitter.prototype.emit is replaced for the whole process: the bot, bot._client,
  bot.inventory, windows, and emitters made by code.
  An event with no listener goes to Node's own emit ('error' with no listener throws).
  Otherwise each listener in a copy of the list is called in order, with the emitter as
  `this`. A listener that throws does not stop the ones after it, and the throw does not
  reach the code that emitted: it is noted as the event listener_error. A listener that
  returns a promise that rejects is noted the same way. emit returns true.
  Listeners added during an emit are not called in that emit; listeners removed during
  it are still called in it.

How long a dig takes, and with what.
  After the first spawn the registry's dig tables are the 1.16.1 game's own, in place of
  Mineflayer's: every block record's hardness, diggable, material and harvestTools, and
  bot.registry.materials. A material is the kind of tool the game gives a speed on the
  block ('pickaxe', 'axe', 'shovel', ...), not 'rock', 'wood' or 'plant'
  (guide("registry-materials"), guide("dig-time")).

bot.dig
  After the first spawn bot.dig is a wrapper: it reads the block's name and position and
  the name of the item in the hand, awaits the library's dig with the same arguments,
  counts the dig for the running job on use when it resolved (`did.dug`), and resolves
  with {dug, at, tool, seconds, gone} (guide("dig-block")). It does not choose or equip
  a tool: it digs with what is in the hand. A rejection passes through.

bot.placeBlock
  After the first spawn bot.placeBlock is a wrapper: it awaits the library's placeBlock,
  then reads the block at the destination, and resolves with {placed, at, seconds}
  (guide("place-block")). It rejects with the library's error only when nothing with a
  full block's shape is there then.

bot._client.write
  Wrapped. A 'chat' packet whose message starts with '/' notes the event command {text}.
  A 'block_place' packet while a block item is held is counted in `did.placed`. With a
  game window, held_item_slot, arm_animation and close_window packets are also shown to
  the window. Each packet is then written as the library writes it.

The inventory after a window closes.
  A set_slot packet with window id -2 (the 1.16 game putting items back into the
  player's inventory by itself) is applied to bot.inventory by the body; the library
  alone leaves it out. The packet's slot is mapped: 0 to 8 -> 36 to 44, 36 -> 8, 37 -> 7,
  38 -> 6, 39 -> 5, 40 -> 45, every other number to itself. A failure is noted as
  error {message: 'inventory slot from the server: ...'}.

A click the server did not take.
  bot.equip, bot.unequip, bot.moveSlotItem, bot.toss and bot.tossStack are tried again, up
  to 2 more times, when the click failed in one of two ways. 'Server rejected transaction':
  after 0.4 s, when the server has sent the inventory again. 'Server didn't respond to
  transaction' (after the library's 5 s; the click went to a window the server no longer has
  open): bot.currentWindow is closed first, so that the click goes to the inventory. Each
  is noted as the event click_rejected {call, try, how, window}.

The cursor after a refused click.
  A set_slot packet with window id -1 and slot -1 (the 1.16 game saying what is on the
  cursor; it sends one, with all the slots, after a click it refused) is applied by the
  body: bot.inventory.selectedItem, and bot.currentWindow.selectedItem when a window is
  open, become the packet's item. The library alone leaves it out. A failure is noted as
  error {message: 'cursor from the server: ...'}.

What the body listens to on the bot.
  spawn, messagestr, death, health, entityHurt, kicked, error, playerCollect, end,
  forcedMove and physicsTick, to note events (guide("run-events")) and to count ticks,
  blocks moved and the times the server put the body back (`did.pulled_back`).
  On bot._client it listens to entity_status and set_slot.

The connection.
  At the bot's 'end' event the body's process ends 50 ms later and the bridge starts a
  new one, which logs in again (guide("run-restart")). bot.quit() and bot.end() from
  code lead there too.

chat(text)
  The Python call: the body calls bot.chat with the text cut to 250 characters, when the
  body is in the world; the answer is {sent}. An error is noted as error {message:
  'chat: ...'}.

What is refused.
  A run while the body is dead or not in the world, and code that does not compile
  (guide("run-gate")). A routine or sense name outside the name rule
  (guide("run-routines")). Nothing else is forbidden: the bot's whole API is reachable
  from code.

With a game window.
  The body copies every packet the game sends the bot to the window, and each physics
  tick in which the body's position or head changed (and once in 20 ticks while it
  stands still) it sends the window the body's position, yaw and pitch.
