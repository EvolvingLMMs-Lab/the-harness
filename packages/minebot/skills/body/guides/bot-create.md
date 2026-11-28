guide("bot-create"): mineflayer.createBot and its options; what the mineflayer module
exports.

mineflayer.createBot(options = {}) -> bot
  Returns the bot (an EventEmitter) at once, before any connection. It writes the
  defaults below into the options object it was given, and hands that same object to
  every plugin as its second argument.
  Steps: 1. makes the bot with bot.end and bot._warn; 2. registers the plugins (they run
  later, at 'inject_allowed'); 3. makes the protocol client with the whole options object
  (or takes options.client); 4. when the client knows the version, sets bot.registry,
  bot.version and bot.supportFeature (guide("bot-connection")) and emits
  'inject_allowed' on the next turn of the event loop.
  Throws at step 4 (from the client's event, not from the createBot call):
    "Server version '<v>' is not supported, no data for version"
    "Server version '<v>' is not supported. Latest supported version is '26.1'."
    "Server version '<v>' is not supported. Oldest supported version is '1.8.8'."

Options read by createBot.
  username            'Player'
  version             false: the client finds the server's version itself; or a string
                      such as '1.16.1'
  client              null: createBot makes a client; or a protocol client to use
  plugins             {}: guide("bot-plugins")
  loadInternalPlugins true: guide("bot-plugins")
  logErrors           true: an 'error' event of the bot is printed with console.log
  hideErrors          false; true: 'error' events are not printed, and bot._warn prints
                      nothing
  brand               'vanilla': the client brand sent at login
  respawn             true: bot.respawn() is called at death; guide("health")
  validateChannelProtocol   set to false by createBot

Options read by the plugins of these pages.
  physicsEnabled      true: start value of bot.physicsEnabled; guide("tick-loop")
  maxCatchupTicks     4: most ticks run in one timer firing; guide("tick-loop")
  chat, colorsEnabled, viewDistance, difficulty, skinParts, mainHand,
  enableTextFiltering     start values of bot.settings; guide("settings")
  The protocol client reads its own options from the same object (host, port, auth and
  others).

The module object (require('mineflayer')).
  createBot
  supportFeature(feature, version)    the value of a feature for a version string
  testedVersions                      array of version strings, '1.8.8' to '26.1'
  latestSupportedVersion '26.1', oldestSupportedVersion '1.8.8'
  Location, Painting, ScoreBoard, BossBar, Particle     classes
  Requiring the module under a Node.js version below 18 prints an error and exits the
  process with code 1.
