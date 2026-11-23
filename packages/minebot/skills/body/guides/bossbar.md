guide("bossbar"): the boss bars the server shows: bot.bossBars, the BossBar object, events.

bot.bossBars                 array of BossBar, one for each bar the server has added and
                             not removed; a new array on every read

Events.
'bossBarCreated' (bossBar)   the server adds a bar. A bar with the same UUID is replaced
'bossBarDeleted' (bossBar)   the server removes a bar. Emitted before the bar leaves
                             bot.bossBars; undefined for a UUID that was not stored
'bossBarUpdated' (bossBar)   the server changes the health, the title, the colour and
                             dividers, or the flags of a stored bar. The object is
                             changed before the event. A change for a UUID that is not
                             stored does nothing

BossBar fields.
bar.entityUUID               the UUID of the bar in the packet (string)
bar.title                    ChatMessage; bar.title.toString() is the plain text
bar.health                   the float in the packet
bar.dividers                 0, 6, 10, 12 or 20, from the packet's number 0 to 4
bar.color                    'pink', 'blue', 'red', 'green', 'yellow', 'purple' or
                             'white', from the packet's number 0 to 6; undefined for
                             another number
bar.shouldDarkenSky          flags & 1: 0 or 1
bar.isDragonBar              flags & 2: 0 or 2
bar.createFog, bar.shouldCreateFog    flags & 4: 0 or 4
bar.flags                    shouldDarkenSky | (isDragonBar << 1) | (createFog << 2),
                             computed from the three stored values above: packet flags 1
                             give 1, packet flags 2 give 4, packet flags 4 give 16

Writing a field (title, health, dividers, color, flags, entityUUID, shouldDarkenSky,
isDragonBar, createFog) changes the object only. dividers and color take the packet's
number and store the mapped value; title takes a JSON string or a plain string and
stores a ChatMessage.
