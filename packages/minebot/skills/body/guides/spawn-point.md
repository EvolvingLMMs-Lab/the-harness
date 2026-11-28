guide("spawn-point"): bot.spawnPoint.

bot.spawnPoint                       Vec3; (0, 0, 0) at creation
  The world spawn position the server last sent in a spawn position packet. Each packet
  puts a new Vec3 here and then emits 'game'. Writing it changes nothing on the server.

'game' ()
  Emitted after each spawn position packet (and at the other moments listed in
  guide("game-state")).

'spawnReset' ()                      guide("bed")
