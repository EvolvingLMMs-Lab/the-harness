guide("time"): bot.time and every field, the 'time' event.

bot.time
  An object. Every field is null until the first time packet of the server. The fields
  are set from each time packet and stay as they are between packets: they do not count
  on by themselves.

  bot.time.time             number: the world's day time in ticks, counted on from day 0
  bot.time.bigTime          the same as a BigInt
  bot.time.timeOfDay        number, 0 to 23999: time modulo 24000
  bot.time.day              number: floor(time / 24000)
  bot.time.isDay            boolean: timeOfDay is at or above 0 and below 13000
  bot.time.moonPhase        number, 0 to 7: day modulo 8
  bot.time.age              number: the age of the world in ticks
  bot.time.bigAge           the same as a BigInt
  bot.time.doDaylightCycle  boolean: false when the packet's time is negative, which is
                            how the server marks that the day time stands still. time
                            and bigTime are then the absolute value.
  bot.time.clocks           {} on 1.16.1: the packet has no clock list

'time' ()
  Emitted after each time packet, with all fields set.

Day time used by another call.
  bot.sleep accepts timeOfDay from 12541 to 23458: guide("bed").
