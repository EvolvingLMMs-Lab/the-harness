guide("body"): the list of the pages on what code on the body calls.

The bot is a Mineflayer bot (mineflayer 4.39.0) in Minecraft 1.16.1. The body is walked
by its navigator: await h.go(goal) walks it to a goal without a stop on the way, by the
route that takes the least time, under the hazards and route rules you put in force
(guide("nav-go")). There is no bot.pathfinder. Code can also press the movement keys
(bot.setControlState) and turn the head (bot.look, bot.lookAt) itself.
guide("name") asks for one page: it is given to you with your next message, and is read
from then on. A page gives, for every call, property, event and setting of its topic: what
it does step by step, when it is over and how it fails, the settings that change it and how
they are set, and the numbers that are fixed. The library's source is in the folder your
first message names (mineflayer/lib/plugins/).

Before code calls a function, read the page that has it. Each page below is listed with the
calls it describes. Code given to run_js or save_routine that calls bot.NAME(...) or
bot.creative.NAME(...) whose page was not read is not run: the answer names the pages and
gives them to you with your next message.

The body has three channels: move (the movement keys), look (the head) and use (the hand:
dig, place, hit, use an item, equip, eat, the inventory and windows). Code uses the
channels its program unit claims (none claimed: all three), and a call on a channel it did
not claim throws. Codes on channels of their own run at the same time. The movement keys
move the body relative to where the head looks. guide("run-channels").

The body acts only on what it can see: bot.dig, bot.activateBlock, bot.openBlock (and so
openContainer, openChest, openFurnace), bot.sleep, bot.craft at a table, bot.attack and
bot.activateEntity fail with "not in sight: ..." when no line from the eyes reaches the block or
entity without a block in between; so do bot.fillBucket for the source it fills from and bot.pourBucket for the cell it pours into. bot.placeBlock fails the same way when the place the block goes to could not be seen from
where the body stands, however the head were turned (the head need not be turned there,
and the face the block is put against need not show). What code can
read of the world (blockAt, findBlocks, entities) is not limited.

The pages by what code is to do. The full list, by topic, follows.
  walk to a place, a block or an entity, or away from one: nav-go
  say what a walk keeps away from and which steps it may take: nav-hazards
  know what a route costs and why one way was taken: nav-cost, nav-steps
  move the body with the keys and the head yourself: control-keys, look, physics-keys,
      physics-collision, physics-server-sync, find-blocks, block-at, raycast
  find blocks and read the world: find-blocks, block-at, block-object, raycast, world-object
  dig a block: dig-block, dig-time, dig-face
  place a block: place-block, place-block-options, equip
  hold and use an item: equip, hand-held-item, hand-use-item, consume
  read the inventory: inventory-read, item-object, inventory-updates
  craft: craft, craft-steps, recipe-find
  smelt: furnace, furnace-progress
  use a chest or another container: chest, chest-items, window-open-close, window-transfer
  find entities and fight: entity-find, entity-names, entity-object, attack
  press keys and turn the head: control-keys, look
  health, food, air, death: health, breath, run-death, spawn-point
  time, weather, sleeping: time, weather, bed
  what a run of code is given and how it ends: run-scope, run-helpers, run-channels,
      run-ending, run-report

Read before the first code, with this list: nothing runs on the body until then.
  minecraft-1-16          what Minecraft: Java Edition 1.16.1 has that the game did not
                          always have: the large updates up to this version that change how
                          it is played.

Code on the body: what it is given and how it runs.
  run-bot                 the bot object code on the body is given; how its calls are gated.
  nav-cost                what a route costs, in seconds: each kind of step, what the body
                          has as a limit, what is yours to say.
  nav-go                  h.go(goal, options) and h.path: goals, options, the report, every
                          reason a walk ends without arriving.
  nav-hazards             hazards (where not to stand, what flies at the body) and route
                          rules (which steps may be taken): defining them, putting them in
                          force, for how long.
                          calls: hazard, route_rule, drop_walking_rule, avoid, unavoid,
                            walking_rules
  nav-steps               what the navigator does at each tick: when the route is searched
                          again, how the keys are chosen, when a step counts as done or
                          failed.
  run-channels            the three channels (move, look, use): what each covers, how code
                          says which it uses, what fails, which codes run at once.
  run-death               what the body does when it dies, while it is dead, and for a
                          respawn.
  run-differences         what this bot has and does that a plain Mineflayer bot does not.
  run-ending              every way a run ends, what signal shows, what is cleared.
  run-events              the events the body and its bridge note: kinds, fields, when.
  run-gate                which codes run at once, and what happens when a run is started.
  run-helpers             the object `h` code on the body is given.
  run-pause               what the body does on a code's channels when that code is paused
                          and resumed.
  run-report              the fields of a run's report; how the did counters are counted,
                          pulled_back among them.
  run-restart             when the body's process is ended and started again; the effects.
  run-result              log, the return value, a thrown error, how values are converted.
  run-routines            how a routine is saved, versioned, and called from code.
  run-scope               how the code given to run_js or save_routine is compiled, and its
                          names.
  run-senses              what a sense's code is given, when it runs, how code reads senses.
  run-state               the state the body reports: every key, what it holds, when it
                          changes; `doing` per running job.
  run-timers              sleep and the timer functions code on the body is given.

Keys, the head and the body's movement.
  control-keys            the seven movement keys: setting, reading and releasing them.
                          calls: bot.clearControlStates, bot.getControlState,
                            bot.setControlState
  elytra                  bot.elytraFly, the elytra flight in the simulation, firework
                          boosts.
                          calls: bot.elytraFly
  look                    turning the head: bot.look, bot.lookAt, yaw and pitch, the turning
                          speed.
                          calls: bot.look, bot.lookAt
  physics-collision       how the simulated body collides with blocks: steps, edges with
                          sneak, bouncing, slowing blocks.
  physics-constants       every field of bot.physics, the numbers the simulation runs on.
  physics-keys            what each movement key does in the simulation, on the ground, in
                          the air and on a ladder, with the speeds.
  physics-liquid          what the simulation does in water and lava, in a bubble column and
                          in a cobweb, with the speeds.
  physics-server-sync     how the body's position and look are sent to the server, the
                          'move' event, and what a position packet from the server (a
                          teleport, a move it did not accept) does: the event pulled_back.
  physics-state           the movement state the simulation keeps on bot.entity, and the
                          effects, enchantments and attributes it reads.
  tick-loop               the physics tick: when it runs, when it stops, bot.physicsEnabled,
                          the 'physicsTick' event.
  tick-wait               bot.waitForTicks: waiting a number of physics ticks.
                          calls: bot.waitForTicks

The body's state, the game and the world's clock.
  bed                     bot.sleep, bot.wake, bot.isABed, bot.isSleeping, every check and
                          error, the 'sleep', 'wake' and 'spawnReset' events.
                          calls: bot.isABed, bot.parseBedMetadata, bot.sleep, bot.wake
  breath                  bot.oxygenLevel and the 'breath' event.
  experience              bot.experience and the 'experience' event.
  fishing                 bot.fish: the steps, what it waits for, how it ends.
                          calls: bot.fish
  game-state              bot.game and all its fields, the 'login' and 'game' events, what a
                          change of dimension does.
  health                  health, food, death, respawn and the 'spawn' event.
                          calls: bot.respawn
  spawn-point             bot.spawnPoint.
  time                    bot.time and every field, the 'time' event.
  weather                 bot.isRaining, bot.rainState, bot.thunderState and their events.

Entities and players.
  attack                  bot.attack and bot.swingArm, hitting an entity.
                          calls: bot.attack, bot.swingArm
  entity-events           every entity event on bot, its arguments and its exact moment.
  entity-find             bot.entities, bot.nearestEntity, bot.entityAtCursor.
                          calls: bot.entityAtCursor, bot.nearestEntity
  entity-names            the values of entity.name, entity.type and entity.kind on 1.16.1.
  entity-object           every field and method of an Entity object.
  entity-own              bot.entity, bot.usingHeldItem, bot.fireworkRocketDuration.
  entity-painting         paintings: block.painting and the Painting object.
  entity-updates          which server packet changes which Entity field, and when.
  entity-use              right-clicking an entity: useOn, activateEntity, activateEntityAt.
                          calls: bot.activateEntity, bot.activateEntityAt, bot.useOn
  explosion               what an explosion packet changes, and bot.getExplosionDamages.
                          calls: bot.getExplosionDamages
  mount-riding            bot.mount, bot.dismount, bot.moveVehicle, bot.vehicle, riding
                          events.
                          calls: bot.dismount, bot.mount, bot.moveVehicle
  place-entity            bot.placeEntity: boats, end crystals, armor stands, spawn eggs.
                          calls: bot._placeEntityWithOptions, bot.placeEntity
  player-list             bot.players, bot.player, bot.findPlayer, the player events.
                          calls: bot.findPlayer, bot.findPlayers

The inventory, items and the hand.
  consume                 bot.consume(): eating or drinking the item in the hand.
                          calls: bot.consume
  creative                the bot.creative calls: setting inventory slots and flying.
                          calls: bot.creative.clearInventory, bot.creative.clearSlot,
                            bot.creative.flyTo, bot.creative.setInventorySlot,
                            bot.creative.startFlying, bot.creative.stopFlying
  equip                   bot.equip, bot.unequip, the equipment destinations and their
                          slots.
                          calls: bot.equip, bot.getEquipmentDestSlot, bot.unequip
  hand-held-item          the held item, the selected hotbar slot, and the 'heldItemChanged'
                          event.
                          calls: bot.setQuickBarSlot, bot.updateHeldItem
  hand-use-item           using the held item (bot.activateItem), filling a bucket
                          (bot.fillBucket) and pouring one (bot.pourBucket), and where a
                          bucket puts and takes its liquid.
                          calls: bot.activateItem, bot.deactivateItem, bot.fillBucket,
                          bot.pourBucket
  inventory-read          bot.inventory, its slot numbers, and the calls that read it.
  inventory-updates       what changes bot.inventory, and its state while another window is
                          open.
                          calls: bot._setSlot, bot._syncWindow
  item-nbt-and-static     Item fields read from NBT (enchantments, names, repair cost) and
                          the static functions of the Item class.
  item-object             the Item object: its plain fields, durability, and how one is
                          made.
  toss                    bot.toss and bot.tossStack: dropping items on the ground;
                          bot.tossedItem.
                          calls: bot.toss, bot.tossStack, bot.tossedItem

Windows.
  window-click            bot.clickWindow: sending one click, its confirmation, time limits
                          and errors.
                          calls: bot.clickWindow
  window-click-modes      what each click mode does to the local slots and cursor of a
                          window once the server accepts it (window.acceptClick).
  window-object           the Window object: its fields and the methods that read it.
  window-object-changes   the Window methods that change the local copy of a window, and the
                          window's slot events.
  window-open-close       opening a window on a block or an entity, bot.currentWindow,
                          closing, and the window events.
                          calls: bot.closeWindow, bot.openBlock, bot.openEntity
  window-transfer         moving items between slots with several clicks: bot.transfer,
                          bot.putSelectedItemRange, bot.putAway, bot.moveSlotItem.
                          calls: bot.moveSlotItem, bot.putAway, bot.putSelectedItemRange,
                            bot.transfer
  window-types            the window types of Minecraft 1.16.1 and their slot layout.

Crafting, furnaces, containers, villagers.
  anvil                   bot.openAnvil and the anvil window: combine and rename.
                          calls: bot.openAnvil
  anvil-cost              how the level cost of an anvil operation is computed (Item.anvil).
  book                    writing and signing a book and quill: bot.writeBook, bot.signBook.
                          calls: bot.signBook, bot.writeBook
  chest                   opening chests and other containers: bot.openContainer, openChest.
                          calls: bot.openContainer
  chest-items             the members of an open container window and where each is
                          described.
  craft                   bot.craft: what it checks, when it ends, every error.
                          calls: bot.craft
  craft-steps             the clicks of one application of a recipe in bot.craft.
  enchant-table           bot.openEnchantmentTable: the window, its options, 'ready'.
                          calls: bot.openEnchantmentTable
  enchant-use             the methods of an open enchanting table: put, enchant, take.
  furnace                 bot.openFurnace and the furnace window: slots, putting in, taking
                          out.
                          calls: bot.openFurnace
  furnace-progress        the fuel and progress values of an open furnace window.
  recipe-find             finding crafting recipes: bot.recipesFor, bot.recipesAll,
                          Recipe.find.
                          calls: bot.recipesAll, bot.recipesFor
  recipe-object           the Recipe object and its RecipeItem entries, field by field.
  villager-open           bot.openVillager: the trading window and the list of trades.
                          calls: bot.openVillager
  villager-trade          bot.trade and villager.trade: how one trade is carried out.
                          calls: bot.trade

Blocks and the world.
  block-action-events     note blocks, pistons, lids, and the breaking of blocks seen.
  block-activate          bot.activateBlock: clicking a block.
                          calls: bot.activateBlock
  block-at                reading the block at a position from the bot's copy of the world.
                          calls: bot._getBlockAtEyeLevel, bot.blockAt, bot.canSeeBlock
  block-events            the block update events and what changes the bot's copy of blocks.
                          calls: bot._updateBlockState
  block-methods           the methods of a Block object and the ways to build one.
  block-object            the fields of a Block object.
  chunk-events            columns loading and unloading, dimension change,
                          waitForChunksToLoad.
                          calls: bot._getDimensionName, bot.waitForChunksToLoad
  command-block           bot.setCommandBlock.
                          calls: bot.setCommandBlock
  dig-block               bot.dig: what it sends, what it waits for, how it ends.
                          calls: bot.canDigBlock, bot.dig, bot.stopDigging
  dig-face                the forceLook and digFace parameters of bot.dig.
  dig-time                bot.digTime and block.digTime: how the time of a dig is counted.
                          calls: bot.digTime
  find-blocks             bot.findBlocks and bot.findBlock: searching the loaded world.
                          calls: bot.findBlock, bot.findBlocks
  location                the Location class: a position split into chunk coordinates.
  place-block             bot.placeBlock: what it sends, what it waits for, its errors.
                          calls: bot.placeBlock
  place-block-options     bot._placeBlockWithOptions and bot._genericPlace.
                          calls: bot._genericPlace, bot._placeBlockWithOptions
  raycast                 rays through the loaded world: what a ray meets, what the head
                          points at, what the eyes see.
                          calls: bot.blockAtCursor, bot.blockAtEntityCursor,
                            bot.blockInSight, bot.entityInSight, bot.inSight
  sign                    writing a sign, reading its text, and the sign events.
                          calls: bot.updateSign
  vec3                    the Vec3 class: every method, and whether it makes a new vector.
  world-columns           the column objects in bot.world, and bot.world.async.
  world-iterators         the iterator classes of prismarine-world.
  world-object            bot.world: direct reads and writes of the bot's copy of the world.

The registry: the game's tables.
  registry-biomes-and-windows
                          the biome and window records of bot.registry.
  registry-block-states   state ids, block properties, collision shapes.
  registry-blocks         the block records of bot.registry: every field and its values.
  registry-effects-enchantments
                          the effect and enchantment records of bot.registry.
  registry-entities       the entity records of bot.registry, field by field.
  registry-items-and-foods
                          the item and food records of bot.registry.
  registry-lookups        bot.registry: every table of game data it holds for 1.16.1.
  registry-loot           bot.registry.blockLoot and entityLoot, the drop tables.
  registry-materials      bot.registry.materials, the table of tool speeds.
  registry-other-tables   language, attributes, instruments, particles and the rest.
  registry-recipes        bot.registry.recipes, the raw crafting recipe table.
  registry-version        bot.registry version fields, version comparisons, supportFeature.
                          calls: bot.supportFeature

Chat.
  chat-events             the events emitted when text arrives from the server.
  chat-message-object     the ChatMessage object: reading it as text, its fields.
  chat-patterns           matching incoming text with regular expressions; waiting for a
                          line.
                          calls: bot.addChatPattern, bot.addChatPatternSet,
                            bot.awaitMessage, bot.chatAddPattern, bot.removeChatPattern
  chat-send               sending chat, commands and whispers; asking the server to complete
                          text.
                          calls: bot.chat, bot.tabComplete, bot.whisper

What the server shows.
  bossbar                 the boss bars the server shows: bot.bossBars, the BossBar object,
                          events.
  particle                the 'particle' event and the Particle object.
  resource-pack           answering the server's offer of a resource pack.
                          calls: bot.acceptResourcePack, bot.denyResourcePack
  scoreboard              scoreboard objectives, their scores, their events.
  sound                   the events emitted when the server plays a sound.
  tablist                 the header and footer of the player list.
  team                    teams: bot.teams, bot.teamMap, the Team object, the team events.
  title                   the events emitted when the server sends a title to the screen.

The bot object and the client's settings.
  bot-connection          the bot object's version fields, bot.supportFeature, the events of
                          the connection, bot.end, bot.quit, being kicked.
                          calls: bot.end, bot.quit
  bot-create              mineflayer.createBot and its options; what the mineflayer module
                          exports.
  bot-internal-helpers    the helper modules inside mineflayer: promise_utils, conversions,
                          math. They are not on the bot; code reaches them with require.
  bot-plugins             bot.loadPlugin, bot.loadPlugins, bot.hasPlugin, and which internal
                          plugins createBot loads.
                          calls: bot.hasPlugin, bot.loadPlugin, bot.loadPlugins
  settings                bot.settings, bot.setSettings, every client setting and its
                          values.
                          calls: bot.setSettings
