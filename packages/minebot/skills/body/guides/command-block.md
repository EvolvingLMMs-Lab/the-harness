guide("command-block"): bot.setCommandBlock.

bot.setCommandBlock(pos, command, options = {})
  Sends the command and the settings of the command block at pos to the server.
  pos: Vec3. command: string.

  Checks, in order; each throws from the call itself.
  1. bot.player.gamemode is not 1 (creative): throws 'The bot has to be in creative mode
     to open the command block window'.
  2. pos is null, or command is null: throws an AssertionError.
  3. The name of bot.blockAt(pos) does not contain 'command_block': throws "The block
     isn't a command block". With the column not loaded it throws a TypeError.

  options (missing fields are written into the object given).
    options.mode           0 sequence, 1 auto, 2 redstone. Default 2.
    options.trackOutput    boolean, default false
    options.conditional    boolean, default false
    options.alwaysActive   boolean, default false

  It sends one message: pos, command, mode, and the three booleans as flags
  (trackOutput 1, conditional 2, alwaysActive 4, added up).
  It returns undefined at once and waits for no answer. The bot's copy of the world is
  not changed by the call.
