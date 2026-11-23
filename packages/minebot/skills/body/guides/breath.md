guide("breath"): bot.oxygenLevel and the 'breath' event.

bot.oxygenLevel                      number, 0 to 20; undefined until the server first
                                     sends the body's air value
  Set from the entity data the server sends for the body itself: the air value divided
  by 15 and rounded. 20 with air; it falls with the head under water. Writing it changes
  nothing on the server.

'breath' ()
  Emitted each time the server sends the body's air value, right after bot.oxygenLevel is
  set, also when the rounded number is the same as before.
