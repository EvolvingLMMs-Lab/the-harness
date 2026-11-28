guide("bot-plugins"): bot.loadPlugin, bot.loadPlugins, bot.hasPlugin, and which internal
plugins createBot loads.

A plugin is a function (bot, options). It is called once with the bot and the createBot
options object, and adds properties, calls and listeners to the bot.

bot.loadPlugin(plugin)
  1. Throws an AssertionError 'plugin needs to be a function' when plugin is not a
     function.
  2. Returns at once when the same function is already in the list.
  3. Adds it to the list. After 'inject_allowed' has been emitted, calls
     plugin(bot, options) at once. Before that, the call happens at 'inject_allowed', in
     list order.
  Returns undefined. An error thrown by the plugin function comes out of loadPlugin (or
  out of the 'inject_allowed' event).

bot.loadPlugins(plugins)
  plugins: an array of functions. Throws an AssertionError 'plugins need to be an array
  of functions' when one element is not a function; then none is loaded. Else calls
  bot.loadPlugin for each, in order.

bot.hasPlugin(plugin) -> boolean
  true when that function is in the list (loaded, or waiting for 'inject_allowed').

'inject_allowed' ()
  Emitted once, one turn of the event loop after the protocol client knows the game
  version. All listed plugins are called in this event. Before it, bot.registry,
  bot.version and bot.supportFeature are set; the calls that plugins add (bot.look,
  bot.setControlState, ...) exist only after it.

Internal plugins, in the order createBot loads them.
  bed, title, block_actions, blocks, book, boss_bar, breath, chat, chest, command_block,
  craft, creative, digging, enchantment_table, entities, experience, explosion, fishing,
  furnace, game, health, inventory, kick, physics, place_block, rain, ray_trace,
  resource_pack, scoreboard, team, settings, simple_inventory, sound, spawn_point,
  tablist, time, villager, anvil, place_entity, generic_place, particle.

The createBot option plugins (an object keyed by name) decides for each.
  plugins[name] === false        the internal plugin of that name is not loaded
  plugins[name] is a function    the internal plugin of that name is not loaded; the
                                 function is loaded after all internal plugins
  plugins[name] is truthy        the internal plugin is loaded, also with
                                 loadInternalPlugins false
  not given                      loaded when loadInternalPlugins is true (the default)
