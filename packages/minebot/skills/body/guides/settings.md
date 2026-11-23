guide("settings"): bot.settings, bot.setSettings, every client setting and its values.

bot.settings
  An object of client settings. Its starting values come from the createBot options of
  the same names. Writing a field does not send anything; bot.setSettings sends.

  chat                 'enabled' (default), 'commandsOnly', 'disabled'. Sent.
  colorsEnabled        boolean, default true. Sent as the chat colours flag.
  viewDistance         'far' (12 chunks, default), 'normal' (10), 'short' (8), 'tiny' (6),
                       or a number above 0 (chunks). Sent.
  mainHand             'right' (default) or 'left'. Sent.
  skinParts            an object of seven booleans, all true by default: showCape,
                       showJacket, showLeftSleeve, showRightSleeve, showLeftPants,
                       showRightPants, showHat. Sent as one number of seven bits.
  locale               not present by default; 'en_US' is sent when it is absent or
                       empty. A string put here by bot.setSettings is sent.
  difficulty           number, default 2. Stored; not sent.
  enableTextFiltering  boolean, default false. Stored; the 1.16.1 packet has no such
                       field.
  enableServerListing  true, whatever the createBot option says. Stored; not in the
                       1.16.1 packet.
  particleStatus       'all'; no createBot option sets it. Stored; not in the 1.16.1
                       packet.

bot.setSettings(settings)
  settings: an object; {} is allowed.
  1. Copies every own field of settings into bot.settings. A skinParts object replaces
     the whole stored skinParts object.
  2. Checks, each with an AssertionError:
     'invalid chat setting: <value>' when chat is not one of the three names;
     'invalid view distance setting: <value>' when viewDistance is not one of the four
       names and not a number above 0;
     'invalid main hand: <value>' when mainHand is not 'left' or 'right'.
     The fields were already copied in step 1 when a check throws.
  3. Sends one client settings packet with locale, view distance, chat mode, chat
     colours, skin parts and main hand.
  Returns undefined. It does not wait for anything.

When the settings are sent without a call.
  At every login packet the module calls bot.setSettings({}): the stored settings go to
  the server once at login.

The view distance is a request to the server. bot.game.serverViewDistance holds the
server's own number.
