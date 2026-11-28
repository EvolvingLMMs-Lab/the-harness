guide("experience"): bot.experience and the 'experience' event.

bot.experience
  An object with three fields, all null until the first experience packet of the server.
  bot.experience.level       number: the experience level
  bot.experience.points      number: total experience points
  bot.experience.progress    number, 0 to 1: how full the bar to the next level is
  All three are set from each experience packet and at no other time.

'experience' ()
  Emitted after each experience packet, with the three fields already set.
